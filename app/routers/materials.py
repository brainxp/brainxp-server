from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, BackgroundTasks, File, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app import queue as Q
from app import schemas as S
from app import tables as T
from app.config import settings
from app.deps import Conn, Me, authorize_subject, is_proxy
from app.errors import Forbidden, Invalid, NotFound, RateLimited
from app.routes import CommitBeforeResponse
from app.security import now
from app.services import documents, storage
from app.services import ledger as L
from app.services import ratelimit as RL
from app.services.generation import CHANNEL

router = APIRouter(tags=["materials"], route_class=CommitBeforeResponse)

_DERIVED = {"times_studied", "question_count", "unfinished"}


def _material_out(
    row, *, times_studied: int, question_count: int,
    unfinished: S.UnfinishedOut | None = None,
) -> S.MaterialOut:
    d = dict(row)
    for k in ("concept_density", "novelty_score"):
        if d.get(k) is not None:
            d[k] = float(d[k])
    base = {k: d.get(k) for k in S.MaterialOut.model_fields if k not in _DERIVED}
    return S.MaterialOut(
        **base, times_studied=times_studied, question_count=question_count,
        unfinished=unfinished,
    )


async def _unfinished(db, material_id: uuid.UUID) -> S.UnfinishedOut | None:
    row = (
        await db.execute(
            select(
                T.quiz_sessions.c.id,
                func.jsonb_array_length(T.quiz_sessions.c.question_order).label("total"),
            )
            .join(T.question_sets, T.question_sets.c.id == T.quiz_sessions.c.question_set_id)
            .where(T.question_sets.c.material_id == material_id,
                   T.quiz_sessions.c.status == "open")
            .order_by(T.quiz_sessions.c.started_at.desc()).limit(1)
        )
    ).mappings().first()
    if not row:
        return None
    answered = (
        await db.execute(
            select(func.count()).select_from(T.quiz_answers)
            .where(T.quiz_answers.c.session_id == row["id"])
        )
    ).scalar_one()
    return S.UnfinishedOut(
        session_id=row["id"], answered=int(answered), total=int(row["total"] or 0)
    )


@router.post("/subjects/{subject_id}/materials", response_model=S.MaterialAcceptedOut,
             status_code=202)
async def upload_material(
    subject_id: uuid.UUID,
    db: Conn,
    me: Me,
    tasks: BackgroundTasks,
    request: Request,
    file: UploadFile = File(...),
):
    await authorize_subject(db, me, subject_id)
    s = settings()

    ip = RL.client_ip(dict(request.headers), request.client.host if request.client else None)
    if not await RL.hit(f"upload:ip:{ip}", RL.UPLOAD_PER_IP):
        raise RateLimited("Terlalu banyak unggahan dari jaringan ini. Coba lagi nanti.")
    if not await RL.hit("upload:global", RL.UPLOAD_GLOBAL):
        raise RateLimited("Antrean penyiapan soal sedang penuh. Coba lagi sebentar.")

    pol = (
        await db.execute(select(T.policies).where(T.policies.c.subject_id == subject_id))
    ).mappings().one()

    method = documents.method_for(documents.classify(file.content_type or ""))
    if method not in (pol["allowed_upload_methods"] or []):
        raise Forbidden(
            "Menyetor lewat foto belum diizinkan oleh aturan."
            if method == "photo"
            else "Menyetor lewat dokumen belum diizinkan oleh aturan."
        )

    data = await file.read()
    if not data:
        raise Invalid("Berkas kosong.")
    documents.guard_size(data, s.max_upload_bytes)

    st = await L.standing(db, subject_id)
    hits = await Q.upload_quota_hit(str(subject_id), st.day.isoformat())
    if hits > s.daily_upload_quota:
        raise RateLimited(
            f"Kuota unggah hari ini ({s.daily_upload_quota} materi) sudah terpakai."
        )

    digest = documents.sha256_bytes(data)

    twin = (
        await db.execute(
            select(T.materials.c.id, T.materials.c.status).where(
                T.materials.c.subject_id == subject_id,
                T.materials.c.content_sha256 == digest,
                T.materials.c.deleted_at.is_(None),
                T.materials.c.status == "ready",
            ).limit(1)
        )
    ).mappings().first()
    if twin:
        return S.MaterialAcceptedOut(
            material_id=twin["id"], status="ready", duplicate_of=twin["id"]
        )

    material_id = uuid.uuid4()
    key = f"{subject_id}/{material_id}/{file.filename or 'materi'}"
    await storage.put(key, data, file.content_type or "application/octet-stream")

    await db.execute(
        T.materials.insert().values(
            id=material_id, subject_id=subject_id,
            source_type=(file.content_type or "").split(";")[0],
            original_name=file.filename, content_sha256=digest,
            byte_size=len(data), page_count=documents.pdf_page_count(data),
            storage_key=key, status="uploaded",
            declared_level=pol["academic_level"],
        )
    )
    tasks.add_task(Q.enqueue, "generate", material_id=str(material_id))
    return S.MaterialAcceptedOut(material_id=material_id, status="uploaded")


@router.get("/materials/{material_id}", response_model=S.MaterialOut)
async def get_material(material_id: uuid.UUID, db: Conn, me: Me):
    row = (
        await db.execute(select(T.materials).where(T.materials.c.id == material_id))
    ).mappings().first()
    if not row or row["deleted_at"]:
        raise NotFound("Materi tidak ditemukan.")
    if is_proxy(me, await authorize_subject(db, me, row["subject_id"])):
        row = {**dict(row), "topic_summary": None}

    qcount = (
        await db.execute(
            select(func.count()).select_from(T.questions)
            .join(T.question_sets, T.question_sets.c.id == T.questions.c.question_set_id)
            .where(T.question_sets.c.material_id == material_id)
        )
    ).scalar_one()
    studied = (
        await db.execute(
            select(func.count()).select_from(T.quiz_sessions)
            .join(T.question_sets, T.question_sets.c.id == T.quiz_sessions.c.question_set_id)
            .where(T.question_sets.c.material_id == material_id,
                   T.quiz_sessions.c.status == "submitted")
        )
    ).scalar_one()

    return _material_out(
        row, times_studied=int(studied), question_count=int(qcount),
        unfinished=await _unfinished(db, material_id),
    )


@router.get("/materials/{material_id}/stream")
async def stream_material(material_id: uuid.UUID, db: Conn, me: Me):
    row = (
        await db.execute(
            select(T.materials.c.subject_id).where(T.materials.c.id == material_id)
        )
    ).first()
    if not row:
        raise NotFound("Materi tidak ditemukan.")
    await authorize_subject(db, me, row[0])

    terminal = ("ready", "rejected", "failed")
    snapshot_key = f"brainxp:material:last:{material_id}"

    async def events():
        pubsub = Q.redis().pubsub()
        await pubsub.subscribe(CHANNEL.format(material_id))
        try:
            snapshot = await Q.redis().get(snapshot_key)
            if snapshot:
                yield f"data: {snapshot}\n\n"
                if json.loads(snapshot).get("stage") in terminal:
                    return

            deadline = asyncio.get_running_loop().time() + 180
            while asyncio.get_running_loop().time() < deadline:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=5.0)
                if msg is not None:
                    yield f"data: {msg['data']}\n\n"
                    if json.loads(msg["data"]).get("stage") in terminal:
                        return
                    continue

                latest = await Q.redis().get(snapshot_key)
                if latest and latest != snapshot:
                    snapshot = latest
                    yield f"data: {latest}\n\n"
                    if json.loads(latest).get("stage") in terminal:
                        return
                    continue
                yield ": keep-alive\n\n"
        finally:
            await pubsub.unsubscribe(CHANNEL.format(material_id))
            await pubsub.aclose()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/subjects/{subject_id}/library", response_model=list[S.MaterialOut])
async def library(subject_id: uuid.UUID, db: Conn, me: Me):
    hidden = is_proxy(me, await authorize_subject(db, me, subject_id))
    rows = (
        await db.execute(
            select(T.materials).where(
                T.materials.c.subject_id == subject_id,
                T.materials.c.deleted_at.is_(None),
                T.materials.c.status.in_(["ready", "generating"]),
            ).order_by(T.materials.c.created_at.desc()).limit(100)
        )
    ).mappings().all()

    out: list[S.MaterialOut] = []
    for r in rows:
        d = dict(r)
        if hidden:
            d["topic_summary"] = None
        studied = (
            await db.execute(
                select(func.count()).select_from(T.quiz_sessions)
                .join(T.question_sets, T.question_sets.c.id == T.quiz_sessions.c.question_set_id)
                .where(T.question_sets.c.material_id == r["id"],
                       T.quiz_sessions.c.status == "submitted")
            )
        ).scalar_one()
        qcount = (
            await db.execute(
                select(func.count()).select_from(T.questions)
                .join(T.question_sets, T.question_sets.c.id == T.questions.c.question_set_id)
                .where(T.question_sets.c.material_id == r["id"])
            )
        ).scalar_one()
        out.append(_material_out(
            d, times_studied=int(studied), question_count=int(qcount),
            unfinished=await _unfinished(db, r["id"]),
        ))
    return out


@router.get("/materials/{material_id}/file")
async def material_file(material_id: uuid.UUID, db: Conn, me: Me):
    row = (
        await db.execute(select(T.materials).where(T.materials.c.id == material_id))
    ).mappings().first()
    if not row or row["deleted_at"]:
        raise NotFound("Materi tidak ditemukan.")
    if is_proxy(me, await authorize_subject(db, me, row["subject_id"])):
        raise Forbidden("Isi materi anak bukan bagian dari laporan orang tua.")
    if not row["storage_key"]:
        raise NotFound("Berkas asli sudah dihapus.")
    return {"url": await storage.signed_url(row["storage_key"]),
            "expires_in": settings().signed_url_ttl_seconds}


@router.patch("/materials/{material_id}/retention", response_model=S.MaterialOut)
async def set_retention(material_id: uuid.UUID, body: S.RetentionIn, db: Conn, me: Me):
    row = (
        await db.execute(select(T.materials).where(T.materials.c.id == material_id))
    ).mappings().first()
    if not row or row["deleted_at"]:
        raise NotFound("Materi tidak ditemukan.")
    if is_proxy(me, await authorize_subject(db, me, row["subject_id"])):
        raise Forbidden("Retensi materi ditentukan pemiliknya.")

    if body.retention_mode == "auto_purge" and row["storage_key"]:
        await storage.delete(row["storage_key"])
        await db.execute(
            T.materials.update().where(T.materials.c.id == material_id)
            .values(retention_mode="auto_purge", storage_key=None, purged_at=now())
        )
    else:
        await db.execute(
            T.materials.update().where(T.materials.c.id == material_id)
            .values(retention_mode=body.retention_mode)
        )
    return await get_material(material_id, db, me)


@router.delete("/materials/{material_id}", status_code=204)
async def delete_material(material_id: uuid.UUID, db: Conn, me: Me):
    row = (
        await db.execute(select(T.materials).where(T.materials.c.id == material_id))
    ).mappings().first()
    if not row:
        raise NotFound("Materi tidak ditemukan.")
    if is_proxy(me, await authorize_subject(db, me, row["subject_id"])):
        raise Forbidden("Materi hanya dapat dihapus pemiliknya.")

    if row["storage_key"]:
        await storage.delete(row["storage_key"])
    await db.execute(
        T.materials.update().where(T.materials.c.id == material_id)
        .values(deleted_at=now(), storage_key=None, purged_at=now())
    )
    await db.execute(
        T.audit_log.insert().values(
            actor_user_id=me.user_id, action="material_deleted", target=str(material_id)
        )
    )
