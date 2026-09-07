from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import asdict
from difflib import SequenceMatcher

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from app import queue as Q
from app import tables as T
from app.services import documents, storage
from app.services import llm as L
from app.services import rules as R
from app.services.llm import PROMPT_VERSION, Attachment, GeneratedQuestion, provider

log = logging.getLogger("brainxp.generation")

CHANNEL = "brainxp:material:{}"


async def publish(material_id: uuid.UUID, payload: dict) -> None:
    await Q.redis().publish(CHANNEL.format(material_id), json.dumps(payload))
    await Q.redis().setex(f"brainxp:material:last:{material_id}", 3600, json.dumps(payload))


async def times_studied(db: AsyncConnection, subject_id: uuid.UUID, content_hash: str) -> int:
    n = (
        await db.execute(
            select(func.count())
            .select_from(T.quiz_sessions)
            .join(T.question_sets, T.question_sets.c.id == T.quiz_sessions.c.question_set_id)
            .join(T.materials, T.materials.c.id == T.question_sets.c.material_id)
            .where(
                T.quiz_sessions.c.subject_id == subject_id,
                T.quiz_sessions.c.status == "submitted",
                T.materials.c.content_sha256 == content_hash,
            )
        )
    ).scalar_one()
    return int(n)


async def near_duplicate_penalty(
    db: AsyncConnection, subject_id: uuid.UUID, topic: str, exclude: uuid.UUID
) -> int:
    if not topic:
        return 0
    rows = (
        await db.execute(
            select(T.materials.c.topic_summary)
            .where(
                T.materials.c.subject_id == subject_id,
                T.materials.c.id != exclude,
                T.materials.c.deleted_at.is_(None),
                T.materials.c.topic_summary.isnot(None),
            )
            .order_by(T.materials.c.created_at.desc())
            .limit(40)
        )
    ).all()
    hits = sum(
        1 for (prev,) in rows
        if SequenceMatcher(None, topic.lower(), (prev or "").lower()).ratio() >= 0.82
    )
    return hits


def _rows_for(qs_id: uuid.UUID, items: list[GeneratedQuestion]) -> list[dict]:
    out = []
    for i, q in enumerate(items):
        out.append({
            "question_set_id": qs_id,
            "ordinal": i,
            "qtype": q.qtype,
            "stem": q.stem,
            "options": q.options,
            "correct_index": q.correct_index,
            "rubric": [c.model_dump() for c in q.rubric] if q.rubric else None,
            "reference_answer": q.reference_answer,
            "source_excerpt": q.source_excerpt,
            "explanation": q.explanation,
            "difficulty": q.difficulty,
            "bloom_level": q.bloom_level,
        })
    return out


def _overflow(q: GeneratedQuestion) -> str | None:
    checks: list[tuple[str, int, int]] = [
        ("stem", len(q.stem), L.STEM_MAX),
        ("source_excerpt", len(q.source_excerpt), L.EXCERPT_MAX),
        ("explanation", len(q.explanation), L.EXPLANATION_MAX),
        ("reference_answer", len(q.reference_answer or ""), L.REFERENCE_MAX),
    ]
    checks += [("option", len(o), L.OPTION_MAX) for o in (q.options or [])]
    for c in q.rubric or []:
        checks.append(("criterion", len(c.criterion), L.CRITERION_MAX))
        checks.append(("indicator", len(c.indicator), L.INDICATOR_MAX))

    for name, size, cap in checks:
        if size > cap:
            return f"{name} {size} melebihi {cap}"
    return None


def _within_limits(q: GeneratedQuestion) -> bool:
    return _overflow(q) is None


def _rejection(q: GeneratedQuestion) -> str | None:
    if not q.stem.strip() or not q.source_excerpt.strip():
        return "empty stem or excerpt"
    over = _overflow(q)
    if over:
        return f"over the length limit: {over}"
    if q.qtype == "essay":
        if not q.rubric or not 2 <= len(q.rubric) <= 5:
            return "incomplete essay rubric"
        if not (q.reference_answer or "").strip():
            return "essay without a reference answer"
        return None
    if not q.options or len(q.options) != 4:
        return "multiple choice without four options"
    if q.correct_index is None or not 0 <= q.correct_index < 4:
        return "answer key out of range"
    cleaned = [o.strip().lower() for o in q.options]
    if len(set(cleaned)) != 4 or any(not o for o in cleaned):
        return "duplicate or empty option"
    banned = ("semua benar", "tidak ada yang benar", "all of the above", "none of the above")
    if any(any(b in o for b in banned) for o in cleaned):
        return "uses a banned option"
    return None


def _keep(items: list[GeneratedQuestion]) -> list[GeneratedQuestion]:
    kept: list[GeneratedQuestion] = []
    for q in items:
        why = _rejection(q)
        if why:
            log.warning("dropped a %s question: %s", q.qtype, why)
        else:
            kept.append(q)
    return kept


def _dedupe(items: list[GeneratedQuestion]) -> list[GeneratedQuestion]:
    kept: list[GeneratedQuestion] = []
    for q in items:
        if all(SequenceMatcher(None, q.stem.lower(), k.stem.lower()).ratio() < 0.85 for k in kept):
            kept.append(q)
    return kept


VISIBILITY_TRIES = 12
VISIBILITY_PAUSE = 0.4


async def _await_material(db: AsyncConnection, material_id: uuid.UUID) -> dict:
    for _ in range(VISIBILITY_TRIES):
        row = (
            await db.execute(select(T.materials).where(T.materials.c.id == material_id))
        ).mappings().first()
        if row:
            return dict(row)
        await asyncio.sleep(VISIBILITY_PAUSE)
    raise LookupError(f"materi {material_id} tidak pernah muncul")


async def run(db: AsyncConnection, material_id: uuid.UUID) -> None:
    mat = await _await_material(db, material_id)
    pol = (
        await db.execute(select(T.policies).where(T.policies.c.subject_id == mat["subject_id"]))
    ).mappings().one()

    async def fail(reason: str) -> None:
        await db.execute(
            T.materials.update().where(T.materials.c.id == material_id)
            .values(status="failed", gate_reason=reason)
        )
        await publish(material_id, {"stage": "failed", "reason": reason})

    await publish(material_id, {"stage": "reading", "ready": 0})
    try:
        raw = await storage.get(mat["storage_key"])
        data, media = await documents.to_attachment_bytes(
            data=raw, media_type=mat["source_type"]
        )
    except Exception as exc:
        log.exception("normalisation failed for %s", material_id)
        return await fail(f"Berkas tidak dapat dibaca: {exc}")

    att = Attachment(media_type=media, data=data)
    llm = provider()

    await db.execute(
        T.materials.update().where(T.materials.c.id == material_id).values(status="validating")
    )
    await publish(material_id, {"stage": "validating", "ready": 0})

    try:
        verdict = await llm.validate_material(att=att, declared_level=pol["academic_level"])
    except Exception as exc:
        log.exception("validation failed for %s", material_id)
        return await fail(f"Materi tidak dapat diperiksa: {exc}")

    seen = await times_studied(db, mat["subject_id"], mat["content_sha256"])
    seen += await near_duplicate_penalty(
        db, mat["subject_id"], verdict.topic_summary, material_id
    )

    gate = R.evaluate_gate(
        declared_level=pol["academic_level"],
        assessed_level=verdict.assessed_level,
        concept_density=verdict.concept_density,
        is_study_material=verdict.is_study_material,
        times_seen=seen,
    )

    await db.execute(
        T.materials.update().where(T.materials.c.id == material_id).values(
            assessed_level=verdict.assessed_level,
            concept_density=round(verdict.concept_density, 3),
            detected_language=verdict.detected_language,
            topic_summary=verdict.topic_summary,
            novelty_score=gate.novelty_factor,
            gate_verdict="accepted" if gate.accepted else "rejected",
            gate_reason=gate.reject_reason or gate.note or None,
            status="generating" if gate.accepted else "rejected",
        )
    )

    if not gate.accepted:
        if mat["storage_key"]:
            await storage.delete(mat["storage_key"])
            await db.execute(
                T.materials.update().where(T.materials.c.id == material_id)
                .values(storage_key=None, purged_at=func.now())
            )
        await publish(material_id, {
            "stage": "rejected",
            "reason": gate.reject_reason,
            "note": gate.note,
            "assessed_level": verdict.assessed_level,
            "declared_level": pol["academic_level"],
        })
        return

    want = int(pol["questions_per_session"])
    _, essays = R.session_mix(want, float(pol["essay_ratio"]))

    qs_id = (
        await db.execute(
            T.question_sets.insert().values(
                material_id=material_id,
                model_id=(getattr(llm, "_s", None) and llm._s.model_generation) or "stub",
                prompt_version=PROMPT_VERSION,
                requested_count=want,
                status="partial",
            ).returning(T.question_sets.c.id)
        )
    ).scalar_one()

    try:
        batch = await llm.generate_questions(
            att=att, count=want, essays=essays,
            academic_level=pol["academic_level"],
            language=pol["question_language"],
        )
    except Exception as exc:
        log.exception("generation failed for %s", material_id)
        return await fail(f"Soal tidak dapat dibuat: {exc}")

    kept = _dedupe(_keep(batch.questions))
    if not kept:
        return await fail("Tidak ada soal yang lolos validasi dari materi ini.")

    await db.execute(T.questions.insert(), _rows_for(qs_id, kept))
    await db.execute(
        T.question_sets.update().where(T.question_sets.c.id == qs_id)
        .values(ready_count=len(kept))
    )
    await publish(material_id, {"stage": "partial", "ready": len(kept),
                                "question_set_id": str(qs_id), "total": want})

    blooms = [
        r[0] for r in (
            await db.execute(
                select(T.questions.c.bloom_level)
                .where(T.questions.c.question_set_id == qs_id)
            )
        ).all()
    ]
    floor_ok = R.bloom_floor_met(blooms, pol["academic_level"])

    ready = len(kept)
    status = "complete" if ready >= want else "degraded"
    await db.execute(
        T.question_sets.update().where(T.question_sets.c.id == qs_id).values(status=status)
    )
    await db.execute(
        T.materials.update().where(T.materials.c.id == material_id).values(status="ready")
    )

    await publish(material_id, {
        "stage": "ready",
        "ready": ready,
        "total": want,
        "status": status,
        "question_set_id": str(qs_id),
        "bloom_floor_met": floor_ok,
        "level_factor": gate.level_factor,
        "novelty_factor": gate.novelty_factor,
        "gate": asdict(gate),
    })
