from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from app import tables as T
from app.db import conn
from app.errors import Forbidden, NotFound, Unauthorized
from app.security import read_access_token

Conn = Annotated[AsyncConnection, Depends(conn)]


@dataclass(frozen=True)
class Caller:
    user_id: uuid.UUID | None
    subject_id: uuid.UUID | None
    role: str
    device_id: uuid.UUID | None

    @property
    def is_parent(self) -> bool:
        return self.role == "parent"

    @property
    def is_child(self) -> bool:
        return self.role == "child"


def revoked_reason(device) -> str | None:
    if device is None:
        return "Perangkat ini tidak dikenal lagi."
    if device["unbound_at"] is not None:
        return "Perangkat ini sudah dikeluarkan. Pasangkan ulang untuk melanjutkan."
    if device["deleted_at"] is not None:
        return "Profil ini sudah dihapus."
    return None


async def require_bound_device(db: AsyncConnection, device_id: uuid.UUID) -> None:
    device = (
        await db.execute(
            select(T.devices.c.unbound_at, T.subjects.c.deleted_at)
            .join(T.subjects, T.subjects.c.id == T.devices.c.subject_id, isouter=True)
            .where(T.devices.c.id == device_id)
        )
    ).mappings().first()
    reason = revoked_reason(device)
    if reason:
        raise Unauthorized(reason)


async def caller(db: Conn, authorization: Annotated[str | None, Header()] = None) -> Caller:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("Header Authorization tidak ada.")
    c = read_access_token(authorization.split(" ", 1)[1].strip())
    as_uuid = lambda v: uuid.UUID(v) if v else None  # noqa: E731
    me = Caller(as_uuid(c.get("uid")), as_uuid(c.get("sid")), c["role"], as_uuid(c.get("did")))
    if me.device_id:
        await require_bound_device(db, me.device_id)
    return me


Me = Annotated[Caller, Depends(caller)]


async def authorize_subject(db: AsyncConnection, me: Caller, subject_id: uuid.UUID) -> dict:
    row = (
        await db.execute(select(T.subjects).where(T.subjects.c.id == subject_id))
    ).mappings().first()
    if not row or row["deleted_at"] is not None:
        raise NotFound("Subjek tidak ditemukan.")

    if me.role in ("child", "personal"):
        if me.subject_id != subject_id:
            raise Forbidden()
        return dict(row)

    if me.role == "parent":
        owns = (
            await db.execute(
                select(T.families.c.id)
                .join(T.family_members, T.family_members.c.family_id == T.families.c.id)
                .where(
                    T.families.c.id == row["family_id"],
                    T.family_members.c.user_id == me.user_id,
                    T.family_members.c.role == "parent",
                )
            )
        ).first()
        if not owns:
            raise Forbidden()
        return dict(row)

    raise Forbidden()


async def require_policy_writer(db: AsyncConnection, me: Caller, subject_id: uuid.UUID) -> dict:
    subject = await authorize_subject(db, me, subject_id)
    if me.role == "child":
        raise Forbidden("Aturan hanya dapat diubah oleh orang tua.")
    return subject


def is_proxy(me: Caller, subject: dict) -> bool:
    return me.is_parent and subject.get("user_id") != me.user_id
