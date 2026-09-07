from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from app import schemas as S
from app import tables as T
from app.security import now
from app.services import apps as A


async def active(db: AsyncConnection, subject_id: uuid.UUID):
    return (
        await db.execute(
            select(T.devices).where(
                T.devices.c.subject_id == subject_id, T.devices.c.unbound_at.is_(None)
            ).order_by(T.devices.c.created_at.desc()).limit(1)
        )
    ).mappings().first()


def as_bound(row) -> S.BoundDeviceOut | None:
    if not row:
        return None
    return S.BoundDeviceOut(
        platform=row["platform"], model_name=row["model_name"],
        last_heartbeat_at=row["last_heartbeat_at"], paired_at=row["created_at"],
    )


async def release(db: AsyncConnection, subject_id: uuid.UUID) -> int:
    ids = [
        r[0] for r in (
            await db.execute(
                select(T.devices.c.id).where(
                    T.devices.c.subject_id == subject_id, T.devices.c.unbound_at.is_(None)
                )
            )
        ).all()
    ]
    if not ids:
        return 0
    await db.execute(
        T.devices.update().where(T.devices.c.id.in_(ids)).values(unbound_at=now())
    )
    await db.execute(
        T.refresh_tokens.update().where(
            T.refresh_tokens.c.device_id.in_(ids),
            T.refresh_tokens.c.revoked_at.is_(None),
        ).values(revoked_at=now())
    )
    await A.forget(db, subject_id)
    return len(ids)
