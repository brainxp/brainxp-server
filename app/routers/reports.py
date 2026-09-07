from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter
from sqlalchemy import func, select

from app import schemas as S
from app import tables as T
from app.config import settings
from app.deps import Conn, Me, authorize_subject
from app.routers.ledger import standing as read_standing
from app.routes import CommitBeforeResponse
from app.security import now
from app.services import apps as A
from app.services import devices as D
from app.services import progress as PR
from app.services import rules as R

router = APIRouter(tags=["reports"], route_class=CommitBeforeResponse)


NAMES_IN_ALERT = 3


def unlocked_new_apps_alert(rows, locked: set[str]) -> str | None:
    fresh = [r["label"] for r in rows if r["package"] not in locked]
    if not fresh:
        return None
    shown = ", ".join(fresh[:NAMES_IN_ALERT])
    rest = len(fresh) - NAMES_IN_ALERT
    tail = f" dan {rest} lainnya" if rest > 0 else ""
    return f"{len(fresh)} aplikasi baru terpasang dan belum dikunci: {shown}{tail}."


@router.get("/subjects/{subject_id}/progress", response_model=S.ProgressOut)
async def progress(subject_id: uuid.UUID, db: Conn, me: Me):
    await authorize_subject(db, me, subject_id)
    await PR.ensure_row(db, subject_id)
    row = (
        await db.execute(select(T.progress).where(T.progress.c.subject_id == subject_id))
    ).mappings().one()
    owned = {
        r["badge_code"]: r["earned_at"] for r in (
            await db.execute(
                select(T.achievements).where(T.achievements.c.subject_id == subject_id)
            )
        ).mappings().all()
    }
    return S.ProgressOut(
        subject_id=subject_id,
        streak_current=row["streak_current"], streak_longest=row["streak_longest"],
        freeze_tokens=row["freeze_tokens"], sessions=row["sessions"],
        correct_total=row["correct_total"], essay_passed=row["essay_passed"],
        badges=[
            S.BadgeOut(code=b.code, name=b.name, hint=b.hint,
                       earned=b.code in owned, earned_at=owned.get(b.code))
            for b in PR.BADGES
        ],
    )


@router.get("/subjects/{subject_id}/report", response_model=S.ReportOut)
async def report(subject_id: uuid.UUID, db: Conn, me: Me, days: int = 7):
    subject = await authorize_subject(db, me, subject_id)
    st = await read_standing(subject_id, db, me)

    pol = (
        await db.execute(
            select(T.policies.c.day_reset_hour, T.policies.c.locked_apps)
            .where(T.policies.c.subject_id == subject_id)
        )
    ).mappings().one()
    reset_hour = pol["day_reset_hour"]
    tz = settings().app_tz
    window = min(max(days, 1), 30)

    entries = (
        await db.execute(
            select(T.time_ledger.c.delta_seconds, T.time_ledger.c.entry_type,
                   T.time_ledger.c.occurred_at)
            .where(
                T.time_ledger.c.subject_id == subject_id,
                T.time_ledger.c.occurred_at >= now() - timedelta(days=window + 1),
            )
        )
    ).mappings().all()

    buckets: dict = {}
    for e in entries:
        k = R.day_key(e["occurred_at"], reset_hour=reset_hour, tz=tz)
        b = buckets.setdefault(k, {"earned": 0, "consumed": 0})
        if e["entry_type"] == "earned":
            b["earned"] += e["delta_seconds"]
        elif e["entry_type"] == "consumed":
            b["consumed"] += -e["delta_seconds"]

    today = R.day_key(now(), reset_hour=reset_hour, tz=tz)
    series = []
    for i in range(window - 1, -1, -1):
        d = today - timedelta(days=i)
        b = buckets.get(d, {"earned": 0, "consumed": 0})
        series.append(S.DayPointOut(day=d, earned_seconds=b["earned"],
                                    consumed_seconds=b["consumed"]))

    studied = (
        await db.execute(
            select(func.count()).select_from(T.quiz_sessions)
            .where(T.quiz_sessions.c.subject_id == subject_id,
                   T.quiz_sessions.c.status == "submitted")
        )
    ).scalar_one()
    prog = (
        await db.execute(select(T.progress).where(T.progress.c.subject_id == subject_id))
    ).mappings().first() or {"correct_total": 0, "essay_passed": 0}

    recent = (
        await db.execute(
            select(T.time_ledger).where(T.time_ledger.c.subject_id == subject_id)
            .order_by(T.time_ledger.c.occurred_at.desc()).limit(10)
        )
    ).mappings().all()

    alerts: list[str] = []
    dev = (
        await db.execute(
            select(T.devices).where(
                T.devices.c.subject_id == subject_id, T.devices.c.unbound_at.is_(None)
            ).order_by(T.devices.c.last_heartbeat_at.desc().nullslast()).limit(1)
        )
    ).mappings().first()
    if not dev:
        if subject["kind"] != "personal":
            alerts.append("Belum ada perangkat yang berpasangan.")
    else:
        if dev["last_heartbeat_at"] and now() - dev["last_heartbeat_at"] > timedelta(minutes=5):
            alerts.append("Perangkat berhenti melapor. Saldo dibekukan sampai terhubung kembali.")
        if dev["guardian_status"] == "disabled":
            alerts.append("Pengawas dinonaktifkan di perangkat.")

    new_apps = unlocked_new_apps_alert(
        await A.newly_installed(db, subject_id, now() - timedelta(days=window)),
        set(pol["locked_apps"] or []),
    )
    if new_apps:
        alerts.append(new_apps)

    flags = (
        await db.execute(
            select(func.count()).select_from(T.guardian_events)
            .where(T.guardian_events.c.subject_id == subject_id,
                   T.guardian_events.c.event_type == "essay_injection_attempt",
                   T.guardian_events.c.occurred_at >= now() - timedelta(days=7))
        )
    ).scalar_one()
    if flags:
        alerts.append(f"{flags} jawaban esai ditandai sebagai upaya mengarahkan penilai.")

    return S.ReportOut(
        subject=S.SubjectOut(
            id=subject["id"], display_name=subject["display_name"],
            academic_level=subject["academic_level"], kind=subject["kind"],
        ),
        standing=st, days=series, materials_studied=int(studied),
        correct_total=int(prog["correct_total"]), essay_passed=int(prog["essay_passed"]),
        recent=[
            S.LedgerEntryOut(delta_seconds=r["delta_seconds"], entry_type=r["entry_type"],
                             note=r["note"], occurred_at=r["occurred_at"])
            for r in recent
        ],
        guardian_alerts=alerts,
        device=D.as_bound(await D.active(db, subject_id)),
    )
