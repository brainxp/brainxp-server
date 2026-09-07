from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app import tables as T
from app.security import now
from app.services import push as PU

log = logging.getLogger("brainxp.guardian")

HEARTBEAT_GRACE = timedelta(minutes=5)
HEARTBEAT_SILENCE = timedelta(minutes=15)
SWEEP_INTERVAL = 120

ACCESSIBILITY_OFF = "accessibility_off"
USAGE_ACCESS_OFF = "usage_access_off"
OVERLAY_OFF = "overlay_off"
PROTECTION_DISABLED = "protection_disabled"
DEVICE_SILENT = "device_silent"

KINDS = (ACCESSIBILITY_OFF, USAGE_ACCESS_OFF, OVERLAY_OFF, PROTECTION_DISABLED, DEVICE_SILENT)

REVOKED = "permission_revoked"
RESTORED = "permission_restored"
FAILING = ("degraded", "disabled")

PERMISSION_KINDS = {
    "accessibility": ACCESSIBILITY_OFF,
    "usage_access": USAGE_ACCESS_OFF,
    "overlay": OVERLAY_OFF,
}

PERMISSION_LABELS = {
    "accessibility": "aksesibilitas",
    "usage_access": "akses penggunaan",
    "overlay": "tampil di atas aplikasi lain",
}

HEADLINES = {
    ACCESSIBILITY_OFF: "Izin aksesibilitas dimatikan",
    USAGE_ACCESS_OFF: "Izin akses penggunaan dimatikan",
    OVERLAY_OFF: "Izin tampil di atas aplikasi lain dimatikan",
    PROTECTION_DISABLED: "Pengawas dimatikan di perangkat",
    DEVICE_SILENT: "Perangkat berhenti melapor",
}

BODIES = {
    ACCESSIBILITY_OFF: "BrainXP tidak lagi dapat mengunci game di ponsel {name}.",
    USAGE_ACCESS_OFF: "BrainXP tidak lagi dapat melihat aplikasi yang dibuka {name}.",
    OVERLAY_OFF: "BrainXP tidak lagi dapat menampilkan layar kunci di ponsel {name}.",
    PROTECTION_DISABLED: "Pengawasan di ponsel {name} sedang tidak aktif.",
    DEVICE_SILENT: "Ponsel {name} berhenti melapor. Saldo waktunya dibekukan.",
}


def protection_lost(previous: str | None, current: str) -> bool:
    return current in FAILING and previous not in FAILING


def protection_regained(previous: str | None, current: str) -> bool:
    return current == "ok" and previous in FAILING


def permission_kind(event: dict) -> str | None:
    return PERMISSION_KINDS.get(str(event.get("permission") or ""))


def revoked_detail(permission: str) -> str:
    label = PERMISSION_LABELS.get(permission, permission)
    return f"Izin {label} dicabut di ponsel anak."


def silence_detail(last_seen: datetime, at: datetime) -> str:
    minutes = max(1, int((at - last_seen).total_seconds() // 60))
    return f"Tidak ada laporan selama {minutes} menit."


def still_open():
    return and_(
        T.guardian_alerts.c.acknowledged_at.is_(None),
        T.guardian_alerts.c.resolved_at.is_(None),
    )


async def raise_alert(
    db: AsyncConnection, *, subject_id: uuid.UUID, kind: str,
    detail: str | None = None, device_id: uuid.UUID | None = None,
) -> int | None:
    stmt = pg_insert(T.guardian_alerts).values(
        subject_id=subject_id, device_id=device_id, kind=kind, detail=detail,
    )
    return (
        await db.execute(
            stmt.on_conflict_do_nothing(
                index_elements=[T.guardian_alerts.c.subject_id, T.guardian_alerts.c.kind],
                index_where=still_open(),
            ).returning(T.guardian_alerts.c.id)
        )
    ).scalar()


async def resolve(db: AsyncConnection, *, subject_id: uuid.UUID, kinds: Sequence[str]) -> None:
    if not kinds:
        return
    await db.execute(
        T.guardian_alerts.update().where(
            T.guardian_alerts.c.subject_id == subject_id,
            T.guardian_alerts.c.kind.in_(kinds),
            still_open(),
        ).values(resolved_at=now())
    )


async def deliver(
    db: AsyncConnection, *, subject_id: uuid.UUID, kind: str,
    alert_id: int, detail: str | None = None,
) -> None:
    name = (
        await db.execute(select(T.subjects.c.display_name).where(T.subjects.c.id == subject_id))
    ).scalar()
    if name is None:
        return
    tokens = await PU.recipients(db, subject_id)
    if not tokens:
        log.info("alert %s for %s has nobody to notify", kind, subject_id)
        return
    note = PU.Notification(
        title=HEADLINES.get(kind, "Peringatan pengawas"),
        body=detail or BODIES.get(kind, "").format(name=name),
        data={"alert_id": alert_id, "kind": kind, "subject_id": subject_id},
    )
    try:
        dead = await PU.sender().send(tokens, note)
    except Exception:
        log.exception("could not deliver alert %s for %s", kind, subject_id)
        return
    await PU.prune(db, dead)


def silent_devices(cutoff: datetime):
    return (
        select(
            T.devices.c.id, T.devices.c.subject_id, T.devices.c.last_heartbeat_at,
        )
        .join(T.subjects, T.subjects.c.id == T.devices.c.subject_id)
        .where(
            T.devices.c.unbound_at.is_(None),
            T.subjects.c.deleted_at.is_(None),
            T.devices.c.last_heartbeat_at.isnot(None),
            T.devices.c.last_heartbeat_at < cutoff,
        )
    )


async def sweep(db: AsyncConnection) -> int:
    at = now()
    rows = (await db.execute(silent_devices(at - HEARTBEAT_SILENCE))).mappings().all()
    raised = 0
    for row in rows:
        detail = silence_detail(row["last_heartbeat_at"], at)
        alert_id = await raise_alert(
            db, subject_id=row["subject_id"], kind=DEVICE_SILENT,
            detail=detail, device_id=row["id"],
        )
        if alert_id is None:
            continue
        raised += 1
        await deliver(
            db, subject_id=row["subject_id"], kind=DEVICE_SILENT,
            alert_id=alert_id, detail=detail,
        )
    return raised
