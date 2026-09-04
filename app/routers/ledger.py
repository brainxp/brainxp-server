from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter
from sqlalchemy import select

from app import schemas as S
from app import tables as T
from app.deps import Conn, Me, authorize_subject, is_proxy
from app.errors import Conflict, Forbidden
from app.routes import CommitBeforeResponse
from app.security import now
from app.services import ledger as L
from app.services import rules as R

router = APIRouter(tags=["ledger"], route_class=CommitBeforeResponse)

HEARTBEAT_GRACE = timedelta(minutes=5)


async def _frozen(db, subject_id: uuid.UUID) -> bool:
    row = (
        await db.execute(
            select(T.devices.c.last_heartbeat_at, T.devices.c.guardian_status)
            .where(T.devices.c.subject_id == subject_id, T.devices.c.unbound_at.is_(None))
            .order_by(T.devices.c.last_heartbeat_at.desc().nullslast())
            .limit(1)
        )
    ).mappings().first()
    if not row:
        return False
    if row["guardian_status"] == "disabled":
        return True
    last = row["last_heartbeat_at"]
    return last is not None and now() - last > HEARTBEAT_GRACE


@router.get("/subjects/{subject_id}/standing", response_model=S.StandingOut)
async def standing(subject_id: uuid.UUID, db: Conn, me: Me):
    await authorize_subject(db, me, subject_id)
    st = await L.standing(db, subject_id)
    prog = (
        await db.execute(
            select(T.progress.c.streak_current, T.progress.c.freeze_tokens)
            .where(T.progress.c.subject_id == subject_id)
        )
    ).mappings().first() or {"streak_current": 0, "freeze_tokens": 0}

    playable = st.playable
    reason = st.block_reason
    if await _frozen(db, subject_id):
        playable, reason = 0, R.BlockReason.GUARDIAN_STALE

    return S.StandingOut(
        balance_seconds=st.balance, playable_seconds=playable,
        daily_cap_seconds=st.daily_cap, spent_today_seconds=st.spent_today,
        idle_days=st.idle_days, idle_days_allowed=st.idle_days_allowed, block_reason=reason,
        seconds_until_reset=st.seconds_until_reset,
        streak_current=int(prog["streak_current"]), freeze_tokens=int(prog["freeze_tokens"]),
    )


@router.post("/subjects/{subject_id}/ledger/sync", response_model=S.StandingOut)
async def sync_consumption(
    subject_id: uuid.UUID, body: list[S.ConsumptionIn], db: Conn, me: Me
):
    if is_proxy(me, await authorize_subject(db, me, subject_id)):
        raise Forbidden("Konsumsi dilaporkan oleh perangkat yang memakainya.")

    for item in body[:200]:
        await L.record_consumption(
            db, subject_id=subject_id, seconds=item.seconds,
            note=f"Bermain {item.app_label}", client_event_id=item.client_event_id,
            device_id=me.device_id, occurred_at=item.occurred_at,
        )
    return await standing(subject_id, db, me)


@router.get("/subjects/{subject_id}/ledger", response_model=list[S.LedgerEntryOut])
async def history(subject_id: uuid.UUID, db: Conn, me: Me, limit: int = 50):
    await authorize_subject(db, me, subject_id)
    rows = (
        await db.execute(
            select(T.time_ledger).where(T.time_ledger.c.subject_id == subject_id)
            .order_by(T.time_ledger.c.occurred_at.desc()).limit(min(limit, 200))
        )
    ).mappings().all()
    return [
        S.LedgerEntryOut(
            delta_seconds=r["delta_seconds"], entry_type=r["entry_type"],
            note=r["note"], occurred_at=r["occurred_at"],
        )
        for r in rows
    ]


@router.post("/subjects/{subject_id}/ledger/adjust", response_model=S.StandingOut)
async def adjust(subject_id: uuid.UUID, body: S.AdjustIn, db: Conn, me: Me):
    await authorize_subject(db, me, subject_id)
    if not me.is_parent:
        raise Forbidden("Hanya orang tua yang dapat menyesuaikan saldo.")

    st = await L.standing(db, subject_id)
    if body.direction == "grant":
        delta, kind = body.seconds, "granted"
    else:
        delta = -min(body.seconds, st.balance)
        kind = "redeemed"
        if delta == 0:
            raise Conflict("Saldo sudah nol, tidak ada yang bisa dikurangi.", code="empty_balance")

    await L.append(
        db, subject_id=subject_id, delta_seconds=delta, entry_type=kind, note=body.note
    )
    await db.execute(
        T.audit_log.insert().values(
            actor_user_id=me.user_id, action=f"ledger_{kind}", target=str(subject_id),
            payload={"seconds": delta, "note": body.note},
        )
    )
    return await standing(subject_id, db, me)
