from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Request
from sqlalchemy import select

from app import schemas as S
from app import tables as T
from app.config import settings
from app.deps import Conn, Me
from app.errors import Conflict, RateLimited, Unauthorized
from app.routes import CommitBeforeResponse
from app.security import (
    hash_password,
    issue_access_token,
    new_chain_id,
    new_opaque_token,
    now,
    sha256,
    verify_password,
)
from app.services import progress as P
from app.services import ratelimit as RL

router = APIRouter(tags=["auth"], route_class=CommitBeforeResponse)

DEFAULT_UPLOAD = ["photo", "document"]


async def _issue_pair(
    db, *, user_id: uuid.UUID | None, subject_id: uuid.UUID | None,
    role: str, device_id: uuid.UUID | None = None, chain: uuid.UUID | None = None,
) -> tuple[str, str, int]:
    access, ttl = issue_access_token(
        user_id=str(user_id) if user_id else None,
        subject_id=str(subject_id) if subject_id else None,
        role=role,
        device_id=str(device_id) if device_id else None,
    )
    raw, digest = new_opaque_token()
    await db.execute(
        T.refresh_tokens.insert().values(
            user_id=user_id, device_id=device_id, token_hash=digest,
            family_chain=chain or new_chain_id(),
            expires_at=now() + timedelta(seconds=settings().refresh_ttl_seconds),
        )
    )
    return access, raw, ttl


@router.post("/auth/register", response_model=S.TokenOut, status_code=201)
async def register(body: S.RegisterIn, db: Conn, request: Request):
    ip = RL.client_ip(dict(request.headers), request.client.host if request.client else None)
    if not await RL.hit(f"register:ip:{ip}", RL.REGISTER_PER_IP):
        raise RateLimited("Terlalu banyak akun dibuat dari jaringan ini. Coba lagi nanti.")

    exists = (
        await db.execute(select(T.users.c.id).where(T.users.c.email == body.email.lower()))
    ).first()
    if exists:
        raise Conflict("Email ini sudah terdaftar.", code="email_taken")

    role = "parent" if body.mode == "family" else "personal"
    user_id = (
        await db.execute(
            T.users.insert().values(
                email=body.email.lower(),
                password_hash=hash_password(body.password),
                role=role,
                display_name=body.display_name,
            ).returning(T.users.c.id)
        )
    ).scalar_one()

    family_id = None
    subject_id = None

    if role == "parent":
        family_id = (
            await db.execute(
                T.families.insert().values(owner_user_id=user_id).returning(T.families.c.id)
            )
        ).scalar_one()
        await db.execute(
            T.family_members.insert().values(
                family_id=family_id, user_id=user_id, role="parent"
            )
        )
    else:
        subject_id = (
            await db.execute(
                T.subjects.insert().values(
                    user_id=user_id, display_name=body.display_name,
                    academic_level="profesional", kind="personal",
                ).returning(T.subjects.c.id)
            )
        ).scalar_one()
        await db.execute(
            T.policies.insert().values(
                subject_id=subject_id, academic_level="profesional",
                allowed_upload_methods=DEFAULT_UPLOAD, updated_by=user_id,
            )
        )
        await P.ensure_row(db, subject_id)

    access, refresh, ttl = await _issue_pair(
        db, user_id=user_id, subject_id=subject_id, role=role
    )
    await db.execute(
        T.audit_log.insert().values(actor_user_id=user_id, action="register", target=role)
    )
    return S.TokenOut(
        access_token=access, refresh_token=refresh, expires_in=ttl, role=role,
        user_id=user_id, subject_id=subject_id, family_id=family_id,
    )


@router.post("/auth/login", response_model=S.TokenOut)
async def login(body: S.LoginIn, db: Conn, request: Request):
    ip = RL.client_ip(dict(request.headers), request.client.host if request.client else None)
    if not await RL.hit(f"login:ip:{ip}", RL.LOGIN_PER_IP):
        raise RateLimited("Terlalu banyak percobaan masuk. Coba lagi nanti.")

    row = (
        await db.execute(select(T.users).where(T.users.c.email == body.email.lower()))
    ).mappings().first()
    if not row or row["deleted_at"] or not row["password_hash"]:
        raise Unauthorized("Email atau kata sandi salah.")
    if not verify_password(row["password_hash"], body.password):
        raise Unauthorized("Email atau kata sandi salah.")

    subject_id = (
        await db.execute(
            select(T.subjects.c.id).where(
                T.subjects.c.user_id == row["id"], T.subjects.c.deleted_at.is_(None)
            )
        )
    ).scalar()
    family_id = (
        await db.execute(
            select(T.family_members.c.family_id).where(T.family_members.c.user_id == row["id"])
        )
    ).scalar()

    access, refresh, ttl = await _issue_pair(
        db, user_id=row["id"], subject_id=subject_id, role=row["role"]
    )
    return S.TokenOut(
        access_token=access, refresh_token=refresh, expires_in=ttl, role=row["role"],
        user_id=row["id"], subject_id=subject_id, family_id=family_id,
    )


@router.post("/auth/refresh", response_model=S.TokenOut)
async def refresh(body: S.RefreshIn, db: Conn):
    digest = sha256(body.refresh_token)
    row = (
        await db.execute(
            select(T.refresh_tokens).where(T.refresh_tokens.c.token_hash == digest)
        )
    ).mappings().first()
    if not row:
        raise Unauthorized("Refresh token tidak dikenal.")

    if row["used_at"] is not None or row["revoked_at"] is not None:
        await db.execute(
            T.refresh_tokens.update()
            .where(T.refresh_tokens.c.family_chain == row["family_chain"])
            .values(revoked_at=now())
        )
        raise Unauthorized("Refresh token dipakai ulang. Seluruh sesi perangkat ini dicabut.")

    if row["expires_at"] <= now():
        raise Unauthorized("Refresh token sudah kedaluwarsa.")

    await db.execute(
        T.refresh_tokens.update()
        .where(T.refresh_tokens.c.id == row["id"]).values(used_at=now())
    )

    if row["user_id"]:
        user = (
            await db.execute(select(T.users).where(T.users.c.id == row["user_id"]))
        ).mappings().one()
        role, user_id = user["role"], user["id"]
        subject_id = (
            await db.execute(
                select(T.subjects.c.id).where(T.subjects.c.user_id == user_id)
            )
        ).scalar()
    else:
        dev = (
            await db.execute(select(T.devices).where(T.devices.c.id == row["device_id"]))
        ).mappings().one()
        role, user_id, subject_id = "child", None, dev["subject_id"]

    access, new_refresh, ttl = await _issue_pair(
        db, user_id=user_id, subject_id=subject_id, role=role,
        device_id=row["device_id"], chain=row["family_chain"],
    )
    return S.TokenOut(
        access_token=access, refresh_token=new_refresh, expires_in=ttl, role=role,
        user_id=user_id, subject_id=subject_id,
    )


@router.post("/auth/logout", status_code=204)
async def logout(body: S.RefreshIn, db: Conn, me: Me):
    digest = sha256(body.refresh_token)
    row = (
        await db.execute(
            select(T.refresh_tokens.c.family_chain)
            .where(T.refresh_tokens.c.token_hash == digest)
        )
    ).first()
    if row:
        await db.execute(
            T.refresh_tokens.update()
            .where(T.refresh_tokens.c.family_chain == row[0]).values(revoked_at=now())
        )
