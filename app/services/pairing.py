from __future__ import annotations

from app import tables as T
from app.db import engine

MAX_ATTEMPTS = 5


def burned(attempts: int) -> bool:
    return attempts > MAX_ATTEMPTS


async def count_attempt(code: str) -> int:
    async with engine().connect() as own:
        attempts = (
            await own.execute(
                T.pairing_codes.update()
                .where(T.pairing_codes.c.code == code)
                .values(attempt_count=T.pairing_codes.c.attempt_count + 1)
                .returning(T.pairing_codes.c.attempt_count)
            )
        ).scalar_one()
        await own.commit()
    return attempts
