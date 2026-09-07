from __future__ import annotations

import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app import schemas as S
from app import tables as T
from app.deps import Conn, Me, authorize_subject
from app.errors import Forbidden, RateLimited
from app.routes import CommitBeforeResponse
from app.services import apps as A
from app.services import ratelimit as RL

router = APIRouter(tags=["apps"], route_class=CommitBeforeResponse)


def _ref(a: A.AppRef) -> S.AppRef:
    return S.AppRef(package=a.package, label=a.label)


@router.put("/devices/apps", response_model=S.AppSyncOut)
async def sync_installed_apps(body: S.AppInventoryIn, db: Conn, me: Me):
    if not me.device_id or not me.subject_id:
        raise Forbidden("Hanya perangkat berpasangan yang dapat mengirim daftar aplikasi.")
    if not await RL.hit(f"apps:{me.subject_id}", RL.APP_SYNC_PER_SUBJECT):
        raise RateLimited("Daftar aplikasi terlalu sering dikirim. Coba lagi nanti.")

    diff = await A.sync(db, me.subject_id, me.device_id, body.apps)
    return S.AppSyncOut(
        first_sync=diff.baseline,
        changed=diff.changed,
        present=diff.present,
        installed=[_ref(a) for a in diff.installed],
        uninstalled=[_ref(a) for a in diff.uninstalled],
        synced_at=diff.at,
    )


@router.get("/subjects/{subject_id}/apps", response_model=S.AppInventoryOut)
async def list_installed_apps(
    subject_id: uuid.UUID,
    db: Conn,
    me: Me,
    include_system: bool = False,
    include_removed: bool = False,
):
    await authorize_subject(db, me, subject_id)
    locked = set(
        (
            await db.execute(
                select(T.policies.c.locked_apps).where(T.policies.c.subject_id == subject_id)
            )
        ).scalar()
        or []
    )
    rows = await A.current(
        db, subject_id, include_system=include_system, include_removed=include_removed
    )
    apps = [
        S.InstalledAppOut(
            package=r["package"], label=r["label"], is_system=r["is_system"],
            version_name=r["version_name"], locked=r["package"] in locked,
            is_new=bool(r["is_new"]), first_seen_at=r["first_seen_at"],
            last_seen_at=r["last_seen_at"], removed_at=r["removed_at"],
        )
        for r in rows
    ]
    return S.AppInventoryOut(
        subject_id=subject_id,
        synced_at=await A.last_sync(db, subject_id),
        total=len(apps),
        locked_count=sum(1 for a in apps if a.locked),
        apps=apps,
        recent_changes=[
            S.AppChangeOut(
                occurred_at=c["occurred_at"],
                installed=[S.AppRef(**a) for a in (c["payload"] or {}).get("installed", [])],
                uninstalled=[S.AppRef(**a) for a in (c["payload"] or {}).get("uninstalled", [])],
            )
            for c in await A.recent_changes(db, subject_id)
        ],
    )
