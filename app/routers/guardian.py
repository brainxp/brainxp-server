from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from sqlalchemy import select

from app import schemas as S
from app import tables as T
from app.deps import Conn, Me, authorize_subject
from app.errors import Forbidden, NotFound
from app.routes import CommitBeforeResponse
from app.security import now
from app.services import guardian as G

router = APIRouter(tags=["guardian"], route_class=CommitBeforeResponse)

FEED_LIMIT = 200

AlertStatus = Literal["open", "acknowledged", "resolved", "all"]


def guarded_subjects(me):
    return (
        select(T.subjects.c.id)
        .join(T.family_members, T.family_members.c.family_id == T.subjects.c.family_id)
        .where(
            T.family_members.c.user_id == me.user_id,
            T.family_members.c.role == "parent",
            T.subjects.c.deleted_at.is_(None),
        )
    )


def status_filter(status: AlertStatus):
    if status == "open":
        return G.still_open()
    if status == "acknowledged":
        return T.guardian_alerts.c.acknowledged_at.isnot(None)
    return T.guardian_alerts.c.resolved_at.isnot(None)


def as_alert(row) -> S.AlertOut:
    return S.AlertOut(
        id=row["id"], subject_id=row["subject_id"], subject_name=row["display_name"],
        kind=row["kind"], detail=row["detail"], created_at=row["created_at"],
        acknowledged_at=row["acknowledged_at"], resolved_at=row["resolved_at"],
    )


@router.get("/alerts", response_model=list[S.AlertOut])
async def list_alerts(
    db: Conn, me: Me,
    subject_id: uuid.UUID | None = None,
    status: AlertStatus = "open",
    since: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=FEED_LIMIT)] = FEED_LIMIT,
):
    if subject_id is not None:
        await authorize_subject(db, me, subject_id)
        scope = T.guardian_alerts.c.subject_id == subject_id
    elif me.is_parent:
        scope = T.guardian_alerts.c.subject_id.in_(guarded_subjects(me))
    elif me.subject_id is not None:
        scope = T.guardian_alerts.c.subject_id == me.subject_id
    else:
        raise Forbidden()

    q = (
        select(T.guardian_alerts, T.subjects.c.display_name)
        .join(T.subjects, T.subjects.c.id == T.guardian_alerts.c.subject_id)
        .where(scope)
    )
    if status != "all":
        q = q.where(status_filter(status))
    if since is not None:
        q = q.where(T.guardian_alerts.c.created_at >= since)

    rows = (
        await db.execute(q.order_by(T.guardian_alerts.c.created_at.desc()).limit(limit))
    ).mappings().all()
    return [as_alert(r) for r in rows]


@router.post("/alerts/{alert_id}/ack", response_model=S.AlertOut)
async def acknowledge_alert(alert_id: int, db: Conn, me: Me):
    row = (
        await db.execute(
            select(T.guardian_alerts, T.subjects.c.display_name)
            .join(T.subjects, T.subjects.c.id == T.guardian_alerts.c.subject_id)
            .where(T.guardian_alerts.c.id == alert_id)
        )
    ).mappings().first()
    if not row:
        raise NotFound("Peringatan tidak ditemukan.")

    await authorize_subject(db, me, row["subject_id"])
    if me.is_child:
        raise Forbidden("Peringatan hanya dapat ditutup oleh orang tua.")

    if row["acknowledged_at"] is not None:
        return as_alert(row)

    seen = now()
    await db.execute(
        T.guardian_alerts.update()
        .where(T.guardian_alerts.c.id == alert_id).values(acknowledged_at=seen)
    )
    return as_alert({**row, "acknowledged_at": seen})
