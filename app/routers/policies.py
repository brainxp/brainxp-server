from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter
from sqlalchemy import select

from app import schemas as S
from app import tables as T
from app.deps import Conn, Me, authorize_subject, require_policy_writer
from app.errors import Conflict, NotFound
from app.security import now

router = APIRouter(tags=["policy"])

WEAKEN_DELAY = timedelta(hours=24)
UNDO_WINDOW = timedelta(minutes=10)

LOOSER_WHEN_HIGHER = {"base_reward_seconds", "daily_cap_seconds", "balance_ceiling_seconds",
                      "initial_grant_seconds"}
LOOSER_WHEN_LOWER = {"questions_per_session"}


def _out(row) -> S.PolicyOut:
    d = dict(row)
    d["essay_ratio"] = float(d["essay_ratio"])
    d["locked_apps"] = list(d["locked_apps"] or [])
    return S.PolicyOut(**d)


async def _row(db, subject_id: uuid.UUID):
    row = (
        await db.execute(select(T.policies).where(T.policies.c.subject_id == subject_id))
    ).mappings().first()
    if not row:
        raise NotFound("Aturan untuk subjek ini belum dibuat.")
    return row


def _is_weakening(current, changes: dict) -> bool:
    for k, v in changes.items():
        if v is None:
            continue
        if k in LOOSER_WHEN_HIGHER and v > current[k]:
            return True
        if k in LOOSER_WHEN_LOWER and v < current[k]:
            return True
        if k == "locked_apps":
            removed = set(current["locked_apps"] or []) - set(v)
            if removed:
                return True
        if k == "essay_ratio" and float(v) < float(current["essay_ratio"]):
            return True
    return False


@router.get("/policies/{subject_id}", response_model=S.PolicyOut)
async def get_policy(subject_id: uuid.UUID, db: Conn, me: Me):
    await authorize_subject(db, me, subject_id)
    return _out(await _row(db, subject_id))


@router.put("/policies/{subject_id}", response_model=S.PolicyChangeOut)
async def put_policy(subject_id: uuid.UUID, body: S.PolicyIn, db: Conn, me: Me):
    await require_policy_writer(db, me, subject_id)
    current = await _row(db, subject_id)
    changes = {k: v for k, v in body.model_dump().items() if v is not None}
    if not changes:
        return S.PolicyChangeOut(applied=False, message="Tidak ada perubahan.")

    subject = (
        await db.execute(select(T.subjects).where(T.subjects.c.id == subject_id))
    ).mappings().one()
    personal = subject["kind"] == "personal"
    weakening = _is_weakening(current, changes)

    if personal and weakening:
        pending_at = now() + WEAKEN_DELAY
        await db.execute(
            T.policies.update().where(T.policies.c.subject_id == subject_id).values(
                pending_weaken_at=pending_at, pending_weaken_payload=changes,
                updated_by=me.user_id, updated_at=now(),
            )
        )
        await db.execute(
            T.audit_log.insert().values(
                actor_user_id=me.user_id, action="policy_weaken_requested",
                target=str(subject_id), payload=changes,
            )
        )
        return S.PolicyChangeOut(
            applied=False, pending_until=pending_at,
            message="Pelonggaran aturan berlaku setelah 24 jam. Aturan lama tetap berjalan.",
        )

    await db.execute(
        T.policies.update().where(T.policies.c.subject_id == subject_id)
        .values(**changes, updated_by=me.user_id, updated_at=now())
    )
    await db.execute(
        T.audit_log.insert().values(
            actor_user_id=me.user_id, action="policy_updated",
            target=str(subject_id), payload=changes,
        )
    )
    return S.PolicyChangeOut(applied=True, message="Aturan diperbarui.")


@router.post("/policies/{subject_id}/pending/apply", response_model=S.PolicyChangeOut)
async def apply_pending(subject_id: uuid.UUID, db: Conn, me: Me):
    await require_policy_writer(db, me, subject_id)
    row = await _row(db, subject_id)
    if not row["pending_weaken_at"]:
        raise NotFound("Tidak ada permintaan tertunda.")
    if row["pending_weaken_at"] > now():
        left = int((row["pending_weaken_at"] - now()).total_seconds())
        raise Conflict(f"Masih menunggu {left // 3600} jam lagi.", code="still_waiting")

    payload = row["pending_weaken_payload"] or {}
    await db.execute(
        T.policies.update().where(T.policies.c.subject_id == subject_id).values(
            **payload, pending_weaken_at=None, pending_weaken_payload=None,
            updated_by=me.user_id, updated_at=now(),
        )
    )
    return S.PolicyChangeOut(applied=True, message="Pelonggaran aturan mulai berlaku.")


@router.delete("/policies/{subject_id}/pending", response_model=S.PolicyChangeOut)
async def cancel_pending(subject_id: uuid.UUID, db: Conn, me: Me):
    await require_policy_writer(db, me, subject_id)
    await db.execute(
        T.policies.update().where(T.policies.c.subject_id == subject_id)
        .values(pending_weaken_at=None, pending_weaken_payload=None, updated_at=now())
    )
    return S.PolicyChangeOut(applied=True, message="Permintaan dibatalkan.")


@router.post("/policies/{subject_id}/locked-apps/{package}", response_model=S.PolicyChangeOut)
async def lock_app(subject_id: uuid.UUID, package: str, db: Conn, me: Me):
    await require_policy_writer(db, me, subject_id)
    row = await _row(db, subject_id)
    apps = list(row["locked_apps"] or [])
    if package in apps:
        return S.PolicyChangeOut(applied=False, message="Aplikasi ini sudah dikunci.")
    apps.append(package)
    await db.execute(
        T.policies.update().where(T.policies.c.subject_id == subject_id)
        .values(locked_apps=apps, updated_by=me.user_id, updated_at=now())
    )
    return S.PolicyChangeOut(applied=True, message=f"{package} dikunci.")


@router.delete("/policies/{subject_id}/locked-apps/{package}", response_model=S.PolicyChangeOut)
async def unlock_app(subject_id: uuid.UUID, package: str, db: Conn, me: Me):
    await require_policy_writer(db, me, subject_id)
    row = await _row(db, subject_id)
    apps = list(row["locked_apps"] or [])
    if package not in apps:
        raise NotFound("Aplikasi ini tidak ada di daftar kunci.")

    subject = (
        await db.execute(select(T.subjects).where(T.subjects.c.id == subject_id))
    ).mappings().one()

    recently_added = (
        row["updated_at"] is not None
        and now() - row["updated_at"] <= UNDO_WINDOW
        and (row["pending_weaken_payload"] or {}).get("__last_locked__") == package
    )

    if subject["kind"] == "personal" and not recently_added:
        pending_at = now() + WEAKEN_DELAY
        await db.execute(
            T.policies.update().where(T.policies.c.subject_id == subject_id).values(
                pending_weaken_at=pending_at,
                pending_weaken_payload={"locked_apps": [a for a in apps if a != package]},
                updated_at=now(),
            )
        )
        return S.PolicyChangeOut(
            applied=False, pending_until=pending_at,
            message=f"{package} tetap terkunci sampai 24 jam berlalu.",
        )

    await db.execute(
        T.policies.update().where(T.policies.c.subject_id == subject_id)
        .values(locked_apps=[a for a in apps if a != package],
                updated_by=me.user_id, updated_at=now())
    )
    return S.PolicyChangeOut(applied=True, message=f"{package} dilepas dari daftar kunci.")
