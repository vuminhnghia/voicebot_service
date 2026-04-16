import asyncio
from functools import partial

import boto3
from boto3 import Session
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
        client_kwargs = dict(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",
            config=Config(s3={"addressing_style": "path"}),
        )
        self._client = Session().client("s3", endpoint_url=endpoint, **client_kwargs)
        # Separate client for presigning so URLs point to the public-facing host
        presign_url = public_endpoint or endpoint
        self._presign_client = (
            Session().client("s3", endpoint_url=presign_url, **client_kwargs)
            if presign_url != endpoint
            else self._client
        )

    async def _run(self, func, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(func, *args, **kwargs))

    async def ensure_bucket(self) -> None:
        try:
            await self._run(self._client.head_bucket, Bucket=self._bucket)
        except ClientError:
            await self._run(self._client.create_bucket, Bucket=self._bucket)

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        import io
        await self._run(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=io.BytesIO(data),
            ContentType=content_type,
        )

    async def get(self, key: str) -> bytes | None:
        try:
            resp = await self._run(self._client.get_object, Bucket=self._bucket, Key=key)
            return resp["Body"].read()
        except ClientError:
            return None

    async def delete(self, key: str) -> None:
        await self._run(self._client.delete_object, Bucket=self._bucket, Key=key)

    async def presign(self, key: str, ttl: int = 3600) -> str:
        return await self._run(
            self._presign_client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=ttl,
        )
