from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis

from app.config import settings

READY = "brainxp:jobs:ready"
BUSY = "brainxp:jobs:busy"

_pool: aioredis.Redis | None = None


def redis() -> aioredis.Redis:
    global _pool
    if _pool is None:
        _pool = aioredis.from_url(
            settings().redis_url,
            decode_responses=True,
            socket_timeout=None,
            socket_connect_timeout=5,
            socket_keepalive=True,
            health_check_interval=30,
            retry_on_timeout=True,
        )
    return _pool


async def close() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


async def enqueue(kind: str, **payload: Any) -> None:
    await redis().lpush(READY, json.dumps({"kind": kind, **payload}))


async def reserve(timeout: int = 5) -> tuple[str, dict] | None:
    try:
        raw = await redis().brpoplpush(READY, BUSY, timeout=timeout)
    except (aioredis.TimeoutError, TimeoutError):
        return None
    if raw is None:
        return None
    return raw, json.loads(raw)


async def acknowledge(raw: str) -> None:
    await redis().lrem(BUSY, 1, raw)


async def requeue_stale() -> int:
    moved = 0
    while await redis().rpoplpush(BUSY, READY):
        moved += 1
    return moved


async def upload_quota_hit(subject_id: str, day_key: str) -> int:
    key = f"brainxp:upload:{subject_id}:{day_key}"
    n = await redis().incr(key)
    if n == 1:
        await redis().expire(key, 48 * 3600)
    return n
