from typing import Any

import aioboto3
import structlog
from botocore.config import Config
from botocore.exceptions import ClientError

from app.domain.ports.object_storage import ObjectStoragePort

logger = structlog.get_logger(__name__)


class SeaweedFSAdapter(ObjectStoragePort):
    def __init__(
        self,
        endpoint: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        public_endpoint: str | None = None,
    ) -> None:
        self._bucket = bucket
        self._endpoint = endpoint
        self._presign_endpoint = public_endpoint or endpoint
        self._session = aioboto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        self._s3_config = Config(s3={"addressing_style": "path"}, region_name="us-east-1")
        self._s3: Any = None
        self._presign_s3: Any = None

    def _make_client(self, endpoint: str):
        return self._session.client("s3", endpoint_url=endpoint, config=self._s3_config)

    async def _init_clients(self) -> None:
        if self._s3 is not None:
            return
        self._s3 = await self._make_client(self._endpoint).__aenter__()
        if self._presign_endpoint != self._endpoint:
            self._presign_s3 = await self._make_client(self._presign_endpoint).__aenter__()
        else:
            self._presign_s3 = self._s3

    async def ensure_bucket(self) -> None:
        await self._init_clients()
        try:
            await self._s3.head_bucket(Bucket=self._bucket)
        except ClientError:
            await self._s3.create_bucket(Bucket=self._bucket)
            logger.info("storage_bucket_created", bucket=self._bucket)

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        await self._init_clients()
        try:
            await self._s3.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)
        except Exception as exc:
            logger.error("storage_put_error", key=key, size=len(data), error=str(exc))
            raise

    async def get(self, key: str) -> bytes | None:
        await self._init_clients()
        try:
            resp = await self._s3.get_object(Bucket=self._bucket, Key=key)
            return await resp["Body"].read()
        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            if error_code not in ("NoSuchKey", "404"):
                logger.error("storage_get_error", key=key, error_code=error_code, error=str(exc))
            return None

    async def delete(self, key: str) -> None:
        await self._init_clients()
        try:
            await self._s3.delete_object(Bucket=self._bucket, Key=key)
        except Exception as exc:
            logger.error("storage_delete_error", key=key, error=str(exc))
            raise

    async def presign(self, key: str, ttl: int = 3600) -> str:
        await self._init_clients()
        try:
            return await self._presign_s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=ttl,
            )
        except Exception as exc:
            logger.error("storage_presign_error", key=key, error=str(exc))
            raise

    async def aclose(self) -> None:
        if self._presign_s3 and self._presign_s3 is not self._s3:
            await self._presign_s3.__aexit__(None, None, None)
        if self._s3:
            await self._s3.__aexit__(None, None, None)
        self._s3 = None
        self._presign_s3 = None
