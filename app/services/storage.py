from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any

from app.config import settings


@lru_cache
def _client() -> Any:
    import boto3
    from botocore.config import Config

    s = settings()
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint_url or None,
        aws_access_key_id=s.s3_access_key or None,
        aws_secret_access_key=s.s3_secret_key or None,
        region_name=s.s3_region,
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
    )


def enabled() -> bool:
    s = settings()
    return bool(s.s3_access_key and s.s3_secret_key)


async def put(key: str, data: bytes, content_type: str) -> None:
    if not enabled():
        return
    s = settings()
    await asyncio.to_thread(
        _client().put_object,
        Bucket=s.s3_bucket, Key=key, Body=data,
        ContentType=content_type, ServerSideEncryption="AES256",
    )


async def get(key: str) -> bytes:
    s = settings()
    obj = await asyncio.to_thread(_client().get_object, Bucket=s.s3_bucket, Key=key)
    return await asyncio.to_thread(obj["Body"].read)


async def signed_url(key: str) -> str | None:
    if not enabled():
        return None
    s = settings()
    return await asyncio.to_thread(
        _client().generate_presigned_url,
        "get_object",
        Params={"Bucket": s.s3_bucket, "Key": key},
        ExpiresIn=s.signed_url_ttl_seconds,
    )


async def delete(key: str) -> None:
    if not enabled():
        return
    s = settings()
    await asyncio.to_thread(_client().delete_object, Bucket=s.s3_bucket, Key=key)
