from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app import tables as T
from app.security import now

CHANGE_EVENT = "apps_changed"
CHANGE_HISTORY_LIMIT = 20


@dataclass(frozen=True)
class AppRef:
    package: str
    label: str


@dataclass(frozen=True)
class Diff:
    installed: list[AppRef]
    uninstalled: list[AppRef]
    present: int
    baseline: bool
    at: datetime

    @property
    def changed(self) -> bool:
        return bool(self.installed or self.uninstalled)


def deduplicate(apps: list) -> list:
    latest: dict[str, object] = {}
    for a in apps:
        latest[a.package] = a
    return list(latest.values())


def compare(known: dict[str, str], incoming: dict[str, str]) -> tuple[list[AppRef], list[AppRef]]:
    added = sorted(set(incoming) - set(known))
    removed = sorted(set(known) - set(incoming))
    return (
        [AppRef(p, incoming[p]) for p in added],
        [AppRef(p, known[p]) for p in removed],
    )


async def sync(
    db: AsyncConnection, subject_id: uuid.UUID, device_id: uuid.UUID | None, apps: list
) -> Diff:
    apps = deduplicate(apps)
    rows = (
        await db.execute(
            select(
                T.installed_apps.c.package,
                T.installed_apps.c.label,
                T.installed_apps.c.removed_at,
            ).where(T.installed_apps.c.subject_id == subject_id)
        )
    ).mappings().all()

    known = {r["package"]: r["label"] for r in rows if r["removed_at"] is None}
    incoming = {a.package: a.label for a in apps}
    installed, uninstalled = compare(known, incoming)
    baseline = not rows
    stamp = now()

    await _upsert(db, subject_id, device_id, apps, stamp)
    if uninstalled:
        await db.execute(
            T.installed_apps.update()
            .where(
                T.installed_apps.c.subject_id == subject_id,
                T.installed_apps.c.package.in_([a.package for a in uninstalled]),
            )
            .values(removed_at=stamp)
        )

    diff = Diff(
        installed=installed, uninstalled=uninstalled,
        present=len(incoming), baseline=baseline, at=stamp,
    )
    if diff.changed and not baseline:
        await db.execute(
            T.guardian_events.insert().values(
                subject_id=subject_id, device_id=device_id, event_type=CHANGE_EVENT,
                payload={
                    "installed": [{"package": a.package, "label": a.label} for a in installed],
                    "uninstalled": [{"package": a.package, "label": a.label} for a in uninstalled],
                },
                occurred_at=stamp,
            )
        )
    return diff


async def _upsert(
    db: AsyncConnection, subject_id: uuid.UUID, device_id: uuid.UUID | None,
    apps: list, stamp: datetime,
) -> None:
    stmt = pg_insert(T.installed_apps)
    stmt = stmt.on_conflict_do_update(
        index_elements=[T.installed_apps.c.subject_id, T.installed_apps.c.package],
        set_={
            "label": stmt.excluded.label,
            "is_system": stmt.excluded.is_system,
            "version_name": stmt.excluded.version_name,
            "device_id": stmt.excluded.device_id,
            "last_seen_at": stmt.excluded.last_seen_at,
            "first_seen_at": case(
                (T.installed_apps.c.removed_at.isnot(None), stmt.excluded.first_seen_at),
                else_=T.installed_apps.c.first_seen_at,
            ),
            "removed_at": None,
        },
    )
    await db.execute(
        stmt,
        [
            {
                "subject_id": subject_id, "package": a.package, "label": a.label,
                "is_system": a.is_system, "version_name": a.version_name,
                "device_id": device_id, "first_seen_at": stamp, "last_seen_at": stamp,
                "removed_at": None,
            }
            for a in apps
        ],
    )


def _baseline_moment(subject_id: uuid.UUID):
    return (
        select(func.min(T.installed_apps.c.first_seen_at))
        .where(T.installed_apps.c.subject_id == subject_id)
        .scalar_subquery()
    )


async def current(
    db: AsyncConnection, subject_id: uuid.UUID, *, include_system: bool, include_removed: bool
):
    q = select(
        T.installed_apps,
        (T.installed_apps.c.first_seen_at > _baseline_moment(subject_id)).label("is_new"),
    ).where(T.installed_apps.c.subject_id == subject_id)
    if not include_system:
        q = q.where(T.installed_apps.c.is_system.is_(False))
    if not include_removed:
        q = q.where(T.installed_apps.c.removed_at.is_(None))
    return (
        await db.execute(
            q.order_by(
                T.installed_apps.c.removed_at.isnot(None),
                func.lower(T.installed_apps.c.label),
            )
        )
    ).mappings().all()


async def last_sync(db: AsyncConnection, subject_id: uuid.UUID) -> datetime | None:
    return (
        await db.execute(
            select(func.max(T.installed_apps.c.last_seen_at))
            .where(T.installed_apps.c.subject_id == subject_id)
        )
    ).scalar()


async def recent_changes(db: AsyncConnection, subject_id: uuid.UUID):
    return (
        await db.execute(
            select(T.guardian_events.c.payload, T.guardian_events.c.occurred_at)
            .where(
                T.guardian_events.c.subject_id == subject_id,
                T.guardian_events.c.event_type == CHANGE_EVENT,
            )
            .order_by(T.guardian_events.c.occurred_at.desc())
            .limit(CHANGE_HISTORY_LIMIT)
        )
    ).mappings().all()


async def newly_installed(db: AsyncConnection, subject_id: uuid.UUID, since: datetime):
    return (
        await db.execute(
            select(T.installed_apps.c.package, T.installed_apps.c.label)
            .where(
                T.installed_apps.c.subject_id == subject_id,
                T.installed_apps.c.removed_at.is_(None),
                T.installed_apps.c.is_system.is_(False),
                T.installed_apps.c.first_seen_at > _baseline_moment(subject_id),
                T.installed_apps.c.first_seen_at >= since,
            )
            .order_by(T.installed_apps.c.first_seen_at.desc())
        )
    ).mappings().all()


async def forget(db: AsyncConnection, subject_id: uuid.UUID) -> None:
    await db.execute(
        T.installed_apps.delete().where(T.installed_apps.c.subject_id == subject_id)
    )
