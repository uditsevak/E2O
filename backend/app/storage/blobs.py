"""Blob storage for raw messages and attachments.

`local` keeps files on disk (dev, tests, single-box pilots). `s3` works with any S3-compatible
store (AWS S3, Cloudflare R2, MinIO). Keys are always prefixed with the workspace id.
"""

import asyncio
import os
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.config import get_settings


class BlobStore(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def exists(self, key: str) -> bool: ...


def raw_message_key(workspace_id: uuid.UUID, source_id: uuid.UUID, sha256: str, ext: str = "eml") -> str:
    return f"ws/{workspace_id}/raw/{source_id}/{sha256[:2]}/{sha256}.{ext}"


def attachment_key(workspace_id: uuid.UUID, sha256: str) -> str:
    return f"ws/{workspace_id}/att/{sha256[:2]}/{sha256}"


def _check_key(key: str) -> None:
    if not key.startswith("ws/") or ".." in key.split("/") or key.startswith("/"):
        raise ValueError("invalid blob key")


class LocalBlobStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        _check_key(key)
        return self.root / key

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            tmp.write_bytes(data)
            os.replace(tmp, path)

        await asyncio.to_thread(write)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).exists)


class S3BlobStore:
    def __init__(
        self,
        bucket: str,
        endpoint_url: str | None,
        region: str | None,
        access_key_id: str | None,
        secret_access_key: str | None,
    ) -> None:
        import boto3

        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
        )

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        _check_key(key)
        await asyncio.to_thread(
            self.client.put_object, Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
        )

    async def get(self, key: str) -> bytes:
        _check_key(key)
        resp = await asyncio.to_thread(self.client.get_object, Bucket=self.bucket, Key=key)
        return await asyncio.to_thread(resp["Body"].read)

    async def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        _check_key(key)
        try:
            await asyncio.to_thread(self.client.head_object, Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise
        return True


@lru_cache
def get_blob_store() -> BlobStore:
    settings = get_settings()
    if settings.storage_backend == "s3":
        if not settings.s3_bucket:
            raise RuntimeError("S3_BUCKET is required when STORAGE_BACKEND=s3")
        return S3BlobStore(
            bucket=settings.s3_bucket,
            endpoint_url=settings.s3_endpoint_url,
            region=settings.s3_region,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=(
                settings.s3_secret_access_key.get_secret_value() if settings.s3_secret_access_key else None
            ),
        )
    return LocalBlobStore(settings.storage_local_dir)
