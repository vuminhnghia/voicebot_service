from typing import Any

import aioboto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.domain.ports.object_storage import ObjectStoragePort


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

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        await self._init_clients()
        await self._s3.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)

    async def get(self, key: str) -> bytes | None:
        await self._init_clients()
        try:
            resp = await self._s3.get_object(Bucket=self._bucket, Key=key)
            return await resp["Body"].read()
        except ClientError:
            return None

    async def delete(self, key: str) -> None:
        await self._init_clients()
        await self._s3.delete_object(Bucket=self._bucket, Key=key)

    async def presign(self, key: str, ttl: int = 3600) -> str:
        await self._init_clients()
        return await self._presign_s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=ttl,
        )

    async def aclose(self) -> None:
        if self._presign_s3 and self._presign_s3 is not self._s3:
            await self._presign_s3.__aexit__(None, None, None)
        if self._s3:
            await self._s3.__aexit__(None, None, None)
        self._s3 = None
        self._presign_s3 = None
