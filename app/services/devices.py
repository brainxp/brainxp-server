from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncConnection

from app import schemas as S
from app import tables as T
from app.security import now
from app.services import apps as A
from app.services import push as PU

REPLACED_EVENT = "device_replaced"


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


def conflicting(subject_id: uuid.UUID, install_binding_hash: str):
    return select(T.devices.c.id, T.devices.c.subject_id).where(
        T.devices.c.unbound_at.is_(None),
        or_(
            T.devices.c.subject_id == subject_id,
            T.devices.c.install_binding_hash == install_binding_hash,
        ),
    )


async def _unbind(db: AsyncConnection, rows: Sequence) -> None:
    ids = [r["id"] for r in rows]
    await db.execute(
        T.devices.update().where(T.devices.c.id.in_(ids)).values(unbound_at=now())
    )
    await db.execute(
        T.refresh_tokens.update().where(
            T.refresh_tokens.c.device_id.in_(ids),
            T.refresh_tokens.c.revoked_at.is_(None),
        ).values(revoked_at=now())
    )
    await PU.revoke_devices(db, ids)
    for subject_id in {r["subject_id"] for r in rows}:
        await A.forget(db, subject_id)


async def displace(
    db: AsyncConnection, subject_id: uuid.UUID, install_binding_hash: str
) -> Sequence:
    rows = (
        await db.execute(conflicting(subject_id, install_binding_hash))
    ).mappings().all()
    if rows:
        await _unbind(db, rows)
    return rows


async def announce_replacement(db: AsyncConnection, displaced: Sequence, device_id: uuid.UUID) -> None:
    if not displaced:
        return
    await db.execute(
        T.guardian_events.insert(),
        [
            {
                "subject_id": r["subject_id"], "device_id": r["id"],
                "event_type": REPLACED_EVENT,
                "payload": {"replaced_by": str(device_id)},
            }
            for r in displaced
        ],
    )


async def release(db: AsyncConnection, subject_id: uuid.UUID) -> int:
    rows = (
        await db.execute(
            select(T.devices.c.id, T.devices.c.subject_id).where(
                T.devices.c.subject_id == subject_id, T.devices.c.unbound_at.is_(None)
            )
        )
    ).mappings().all()
    if not rows:
        return 0
    await _unbind(db, rows)
    return len(rows)
