from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app import tables as T
from app.config import settings
from app.security import now
from app.services import rules as R


@dataclass(frozen=True)
class Standing:
    balance: int
    daily_cap: int
    spent_today: int
    playable: int
    block_reason: str
    ceiling: int
    points: int
    seconds_until_reset: int
    day: date


async def balance(db: AsyncConnection, subject_id: uuid.UUID) -> int:
    total = (
        await db.execute(
            select(func.coalesce(func.sum(T.time_ledger.c.delta_seconds), 0))
            .where(T.time_ledger.c.subject_id == subject_id)
        )
    ).scalar_one()
    return max(0, int(total))


async def spent_today(db: AsyncConnection, subject_id: uuid.UUID, day: date) -> int:
    v = (
        await db.execute(
            select(T.daily_usage.c.spent_seconds)
            .where(T.daily_usage.c.subject_id == subject_id, T.daily_usage.c.day_key == day)
        )
    ).scalar()
    return int(v or 0)


async def standing(db: AsyncConnection, subject_id: uuid.UUID) -> Standing:
    pol = (
        await db.execute(select(T.policies).where(T.policies.c.subject_id == subject_id))
    ).mappings().one()
    tz = settings().app_tz
    moment = now()
    day = R.day_key(moment, reset_hour=pol["day_reset_hour"], tz=tz)

    bal = await balance(db, subject_id)
    spent = await spent_today(db, subject_id, day)
    pts = (
        await db.execute(select(T.progress.c.points).where(T.progress.c.subject_id == subject_id))
    ).scalar() or 0

    return Standing(
        balance=bal,
        daily_cap=pol["daily_cap_seconds"],
        spent_today=spent,
        playable=R.playable_seconds(balance=bal, daily_cap=pol["daily_cap_seconds"], spent_today=spent),
        block_reason=R.block_reason(
            balance=bal, daily_cap=pol["daily_cap_seconds"], spent_today=spent
        ),
        ceiling=pol["balance_ceiling_seconds"],
        points=int(pts),
        seconds_until_reset=R.seconds_until_reset(
            moment, reset_hour=pol["day_reset_hour"], tz=tz
        ),
        day=day,
    )


async def append(
    db: AsyncConnection,
    *,
    subject_id: uuid.UUID,
    delta_seconds: int,
    entry_type: str,
    note: str | None = None,
    ref_id: uuid.UUID | None = None,
    client_event_id: str | None = None,
    device_id: uuid.UUID | None = None,
    occurred_at: datetime | None = None,
) -> bool:
    stmt = pg_insert(T.time_ledger).values(
        subject_id=subject_id,
        delta_seconds=int(delta_seconds),
        entry_type=entry_type,
        note=note,
        ref_id=ref_id,
        client_event_id=client_event_id,
        device_id=device_id,
        occurred_at=occurred_at or now(),
    )
    if client_event_id:
        stmt = stmt.on_conflict_do_nothing(
            index_elements=[T.time_ledger.c.subject_id, T.time_ledger.c.client_event_id]
        )
    result = await db.execute(stmt)
    return bool(result.rowcount)


async def add_usage(
    db: AsyncConnection, *, subject_id: uuid.UUID, day: date, seconds: int
) -> None:
    stmt = pg_insert(T.daily_usage).values(
        subject_id=subject_id, day_key=day, spent_seconds=int(seconds)
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[T.daily_usage.c.subject_id, T.daily_usage.c.day_key],
            set_={"spent_seconds": T.daily_usage.c.spent_seconds + int(seconds)},
        )
    )


async def record_consumption(
    db: AsyncConnection,
    *,
    subject_id: uuid.UUID,
    seconds: int,
    note: str,
    client_event_id: str | None,
    device_id: uuid.UUID | None,
    occurred_at: datetime | None = None,
) -> bool:
    st = await standing(db, subject_id)
    capped = max(0, min(int(seconds), st.balance, st.daily_cap - st.spent_today))
    if capped == 0:
        return False

    wrote = await append(
        db, subject_id=subject_id, delta_seconds=-capped, entry_type="consumed",
        note=note, client_event_id=client_event_id, device_id=device_id,
        occurred_at=occurred_at,
    )
    if wrote:
        await add_usage(db, subject_id=subject_id, day=st.day, seconds=capped)
    return wrote


async def credit_reward(
    db: AsyncConnection, *, subject_id: uuid.UUID, gross_seconds: float,
    note: str, ref_id: uuid.UUID | None,
) -> R.Settlement:
    st = await standing(db, subject_id)
    s = R.settle(gross_seconds, balance=st.balance, ceiling=st.ceiling)

    if s.to_balance > 0:
        await append(
            db, subject_id=subject_id, delta_seconds=s.to_balance,
            entry_type="earned", note=note, ref_id=ref_id,
        )
    if s.overflow_points > 0:
        await db.execute(
            T.progress.update()
            .where(T.progress.c.subject_id == subject_id)
            .values(points=T.progress.c.points + s.overflow_points)
        )
        await append(
            db, subject_id=subject_id, delta_seconds=0, entry_type="overflow",
            note=f"{s.overflow_points} poin dari kelebihan plafon", ref_id=ref_id,
        )
    return s
