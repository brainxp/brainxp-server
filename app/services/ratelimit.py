from __future__ import annotations

from dataclasses import dataclass

from app import queue as Q


@dataclass(frozen=True)
class Window:
    limit: int
    seconds: int


PAIR_PER_IP = Window(limit=10, seconds=600)
PAIR_GLOBAL = Window(limit=120, seconds=600)
LOGIN_PER_IP = Window(limit=15, seconds=600)


def exceeded(count: int, window: Window) -> bool:
    return count > window.limit


def retry_after(window: Window) -> int:
    return window.seconds


def client_ip(headers: dict[str, str], peer: str | None) -> str:
    real = headers.get("x-real-ip")
    if real and real.strip():
        return real.strip()
    forwarded = headers.get("x-forwarded-for")
    if forwarded and forwarded.strip():
        return forwarded.split(",")[-1].strip()
    return peer or "unknown"


async def hit(bucket: str, window: Window) -> bool:
    key = f"brainxp:rl:{bucket}"
    redis = Q.redis()
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window.seconds)
    return not exceeded(count, window)
