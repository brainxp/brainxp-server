from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Request
from sqlalchemy import select

from app import schemas as S
from app import tables as T
from app.deps import Conn, Me, authorize_subject
from app.errors import Conflict, Forbidden, NotFound, RateLimited
from app.security import (
    issue_access_token,
    new_device_secret,
    new_opaque_token,
    new_pairing_code,
    now,
    sha256,
)
from app.services import progress as P
from app.services import ratelimit as RL

router = APIRouter(tags=["family"])

PAIRING_TTL = 600
PAIRING_MAX_ATTEMPTS = 5


async def _my_family(db, me) -> uuid.UUID:
    fid = (
        await db.execute(
            select(T.family_members.c.family_id).where(
                T.family_members.c.user_id == me.user_id,
                T.family_members.c.role == "parent",
            )
        )
    ).scalar()
    if not fid:
        raise Forbidden("Akun ini bukan orang tua di keluarga mana pun.")
    return fid


@router.get("/subjects", response_model=list[S.SubjectOut])
async def list_subjects(db: Conn, me: Me):
    if me.role in ("child", "personal"):
        rows = (
            await db.execute(
                select(T.subjects).where(T.subjects.c.id == me.subject_id)
            )
        ).mappings().all()
    else:
        fid = await _my_family(db, me)
        rows = (
            await db.execute(
                select(T.subjects).where(
                    T.subjects.c.family_id == fid, T.subjects.c.deleted_at.is_(None)
                ).order_by(T.subjects.c.created_at)
            )
        ).mappings().all()
    return [S.SubjectOut(**{k: r[k] for k in ("id", "display_name", "academic_level", "kind")})
            for r in rows]


@router.post("/subjects", response_model=S.SubjectOut, status_code=201)
async def create_child(body: S.ChildIn, db: Conn, me: Me):
    if not me.is_parent:
        raise Forbidden("Hanya orang tua yang dapat menambah anak.")
    fid = await _my_family(db, me)

    sid = (
        await db.execute(
            T.subjects.insert().values(
                family_id=fid, display_name=body.display_name,
                academic_level=body.academic_level, kind="child",
            ).returning(T.subjects.c.id)
        )
    ).scalar_one()
    await db.execute(
        T.policies.insert().values(
            subject_id=sid, academic_level=body.academic_level,
            question_language=body.question_language,
            allowed_upload_methods=["photo", "document"], updated_by=me.user_id,
        )
    )
    await P.ensure_row(db, sid)
    await db.execute(
        T.audit_log.insert().values(
            actor_user_id=me.user_id, action="create_child", target=str(sid)
        )
    )
    return S.SubjectOut(
        id=sid, display_name=body.display_name,
        academic_level=body.academic_level, kind="child",
    )


@router.post("/subjects/self", response_model=S.SubjectOut, status_code=201)
async def create_own_subject(body: S.SelfSubjectIn, db: Conn, me: Me):
    if not me.is_parent:
        raise Forbidden("Hanya orang tua yang dapat menambahkan dirinya sendiri.")
    fid = await _my_family(db, me)

    mine = (
        await db.execute(
            select(T.subjects.c.id).where(
                T.subjects.c.user_id == me.user_id,
                T.subjects.c.kind == "personal",
                T.subjects.c.deleted_at.is_(None),
            )
        )
    ).first()
    if mine:
        raise Conflict("Aturan untuk diri sendiri sudah aktif.", code="self_subject_exists")

    owner = (
        await db.execute(select(T.users.c.display_name).where(T.users.c.id == me.user_id))
    ).scalar_one()

    sid = (
        await db.execute(
            T.subjects.insert().values(
                family_id=fid, user_id=me.user_id, display_name=owner,
                academic_level=body.academic_level, kind="personal",
            ).returning(T.subjects.c.id)
        )
    ).scalar_one()
    await db.execute(
        T.policies.insert().values(
            subject_id=sid, academic_level=body.academic_level,
            question_language=body.question_language,
            allowed_upload_methods=["photo", "document"], updated_by=me.user_id,
        )
    )
    await P.ensure_row(db, sid)
    await db.execute(
        T.audit_log.insert().values(
            actor_user_id=me.user_id, action="create_self_subject", target=str(sid)
        )
    )
    return S.SubjectOut(
        id=sid, display_name=owner, academic_level=body.academic_level, kind="personal",
    )


@router.post("/subjects/{subject_id}/pairing-code", response_model=S.PairingCodeOut)
async def issue_pairing_code(subject_id: uuid.UUID, db: Conn, me: Me):
    if not me.is_parent:
        raise Forbidden("Hanya orang tua yang dapat menerbitkan kode.")
    subject = await authorize_subject(db, me, subject_id)

    await db.execute(
        T.pairing_codes.delete().where(
            T.pairing_codes.c.subject_id == subject_id,
            T.pairing_codes.c.consumed_at.is_(None),
        )
    )

    for _ in range(5):
        code = new_pairing_code()
        clash = (
            await db.execute(
                select(T.pairing_codes.c.code).where(
                    T.pairing_codes.c.code == code,
                    T.pairing_codes.c.expires_at > now(),
                )
            )
        ).first()
        if not clash:
            break
    else:
        raise Conflict("Tidak dapat menerbitkan kode saat ini. Coba lagi.")

    expires = now() + timedelta(seconds=PAIRING_TTL)
    await db.execute(
        T.pairing_codes.insert().values(
            code=code, family_id=subject["family_id"], subject_id=subject_id,
            issued_by=me.user_id, expires_at=expires,
        )
    )
    return S.PairingCodeOut(
        code=code, subject_id=subject_id, expires_at=expires,
        attempts_allowed=PAIRING_MAX_ATTEMPTS,
    )


@router.post("/devices/check-binding", response_model=S.BindingCheckOut)
async def check_binding(body: S.BindingCheckIn, db: Conn):
    digest = sha256(body.install_binding)
    row = (
        await db.execute(
            select(T.devices.c.subject_id, T.subjects.c.display_name, T.subjects.c.family_id)
            .join(T.subjects, T.subjects.c.id == T.devices.c.subject_id)
            .where(
                T.devices.c.install_binding_hash == digest,
                T.devices.c.unbound_at.is_(None),
            )
        )
    ).mappings().first()
    if not row:
        return S.BindingCheckOut(bound=False)
    return S.BindingCheckOut(
        bound=True, subject_name=row["display_name"], family_mode=row["family_id"] is not None
    )


@router.post("/devices/pair", response_model=S.TokenOut)
async def pair_device(body: S.PairIn, db: Conn, request: Request):
    ip = RL.client_ip(dict(request.headers), request.client.host if request.client else None)
    within_ip = await RL.hit(f"pair:ip:{ip}", RL.PAIR_PER_IP)
    within_all = await RL.hit("pair:global", RL.PAIR_GLOBAL)
    if not (within_ip and within_all):
        raise RateLimited("Terlalu banyak percobaan pairing. Coba lagi nanti.")

    row = (
        await db.execute(
            select(T.pairing_codes).where(T.pairing_codes.c.code == body.code)
        )
    ).mappings().first()

    if not row:
        raise NotFound("Kode tidak dikenal.")
    if row["consumed_at"] is not None:
        raise Conflict("Kode ini sudah dipakai.", code="code_used")
    if row["expires_at"] <= now():
        raise Conflict("Kode sudah kedaluwarsa. Minta yang baru.", code="code_expired")

    await db.execute(
        T.pairing_codes.update().where(T.pairing_codes.c.code == row["code"])
        .values(attempt_count=T.pairing_codes.c.attempt_count + 1)
    )

    secret_raw, secret_hash = new_device_secret()
    device_id = (
        await db.execute(
            T.devices.insert().values(
                subject_id=row["subject_id"],
                device_secret_hash=secret_hash,
                install_binding_hash=sha256(body.install_binding),
                platform=body.platform,
                model_name=body.model_name,
                guardian_status="unknown",
                last_heartbeat_at=now(),
            ).returning(T.devices.c.id)
        )
    ).scalar_one()

    await db.execute(
        T.pairing_codes.update().where(T.pairing_codes.c.code == row["code"])
        .values(consumed_at=now())
    )

    access, ttl = issue_access_token(
        user_id=None, subject_id=str(row["subject_id"]), role="child", device_id=str(device_id)
    )
    raw, digest = new_opaque_token()
    from datetime import timedelta as _td

    from app.config import settings as _s
    from app.security import new_chain_id
    await db.execute(
        T.refresh_tokens.insert().values(
            user_id=None, device_id=device_id, token_hash=digest,
            family_chain=new_chain_id(),
            expires_at=now() + _td(seconds=_s().refresh_ttl_seconds),
        )
    )
    await db.execute(
        T.audit_log.insert().values(
            actor_user_id=row["issued_by"], action="device_paired", target=str(device_id)
        )
    )
    return S.TokenOut(
        access_token=access, refresh_token=raw, expires_in=ttl, role="child",
        subject_id=row["subject_id"], device_secret=secret_raw,
    )


@router.post("/devices/heartbeat", status_code=204)
async def heartbeat(body: S.HeartbeatIn, db: Conn, me: Me):
    if not me.device_id:
        raise Forbidden("Hanya perangkat berpasangan yang dapat melapor.")
    await db.execute(
        T.devices.update().where(T.devices.c.id == me.device_id)
        .values(guardian_status=body.guardian_status, last_heartbeat_at=now())
    )
    for ev in body.events[:20]:
        await db.execute(
            T.guardian_events.insert().values(
                device_id=me.device_id, subject_id=me.subject_id,
                event_type=str(ev.get("type", "unknown"))[:60], payload=ev,
            )
        )
