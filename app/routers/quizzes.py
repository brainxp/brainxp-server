from __future__ import annotations

import random
import uuid

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app import schemas as S
from app import tables as T
from app.deps import Conn, Me, authorize_subject
from app.errors import Conflict, Forbidden, Invalid, NotFound
from app.security import now
from app.services import grading
from app.services import ledger as L
from app.services import progress as PR
from app.services import rules as R

router = APIRouter(tags=["quiz"])


def _public(q, perm: list[int]) -> S.QuestionPublic:
    options = None
    if q["qtype"] == "mcq" and q["options"]:
        options = [q["options"][i] for i in perm]
    return S.QuestionPublic(
        id=q["id"], ordinal=q["ordinal"], qtype=q["qtype"], stem=q["stem"],
        options=options, difficulty=q["difficulty"], bloom_level=q["bloom_level"],
        source_excerpt=q["source_excerpt"],
        rubric_criteria=[c["criterion"] for c in (q["rubric"] or [])] if q["qtype"] == "essay" else None,
        type_factor=R.TYPE_FACTOR[q["qtype"]],
        difficulty_factor=R.DIFFICULTY_FACTOR[q["difficulty"]],
    )


async def _load(db, session_id: uuid.UUID):
    ses = (
        await db.execute(select(T.quiz_sessions).where(T.quiz_sessions.c.id == session_id))
    ).mappings().first()
    if not ses:
        raise NotFound("Sesi tidak ditemukan.")
    return ses


@router.post("/subjects/{subject_id}/quizzes", response_model=S.QuizOut, status_code=201)
async def start_quiz(subject_id: uuid.UUID, body: S.QuizStartIn, db: Conn, me: Me):
    await authorize_subject(db, me, subject_id)
    if me.is_parent:
        raise Forbidden("Sesi dikerjakan oleh pemilik materi.")

    mat = (
        await db.execute(select(T.materials).where(T.materials.c.id == body.material_id))
    ).mappings().first()
    if not mat or mat["subject_id"] != subject_id or mat["deleted_at"]:
        raise NotFound("Materi tidak ditemukan.")
    if mat["status"] == "rejected":
        raise Conflict(f"Materi ini ditolak: {mat['gate_reason']}", code="material_rejected")
    if mat["status"] not in ("generating", "ready"):
        raise Conflict("Soal belum siap. Tunggu proses penyiapan selesai.", code="not_ready")

    qs = (
        await db.execute(
            select(T.question_sets).where(T.question_sets.c.material_id == body.material_id)
            .order_by(T.question_sets.c.generated_at.desc()).limit(1)
        )
    ).mappings().first()
    if not qs or qs["ready_count"] == 0:
        raise Conflict("Belum ada soal yang siap.", code="not_ready")

    open_session = (
        await db.execute(
            select(T.quiz_sessions.c.id).where(
                T.quiz_sessions.c.subject_id == subject_id,
                T.quiz_sessions.c.question_set_id == qs["id"],
                T.quiz_sessions.c.status == "open",
            ).order_by(T.quiz_sessions.c.started_at.desc()).limit(1)
        )
    ).scalar()
    if open_session:
        return await get_quiz(open_session, db, me)

    pol = (
        await db.execute(select(T.policies).where(T.policies.c.subject_id == subject_id))
    ).mappings().one()
    rows = (
        await db.execute(
            select(T.questions).where(T.questions.c.question_set_id == qs["id"])
            .order_by(T.questions.c.ordinal)
        )
    ).mappings().all()

    order = [str(r["id"]) for r in rows]
    random.shuffle(order)
    perms = {
        str(r["id"]): random.sample(range(len(r["options"])), len(r["options"]))
        for r in rows if r["qtype"] == "mcq" and r["options"]
    }

    times = (
        await db.execute(
            select(T.quiz_sessions.c.id).where(
                T.quiz_sessions.c.subject_id == subject_id,
                T.quiz_sessions.c.question_set_id == qs["id"],
                T.quiz_sessions.c.status == "submitted",
            )
        )
    ).all()
    novelty = R.novelty_factor(len(times))
    level = R.level_factor(pol["academic_level"], mat["assessed_level"] or pol["academic_level"])

    session_id = (
        await db.execute(
            T.quiz_sessions.insert().values(
                subject_id=subject_id, question_set_id=qs["id"],
                question_order=order, option_permutation=perms,
                level_factor=level, novelty_factor=novelty,
                base_reward_seconds=pol["base_reward_seconds"],
                is_replay=bool(times),
            ).returning(T.quiz_sessions.c.id)
        )
    ).scalar_one()

    by_id = {str(r["id"]): r for r in rows}
    questions = [_public(by_id[qid], perms.get(qid, [])) for qid in order]

    return S.QuizOut(
        session_id=session_id, material_id=body.material_id, title=mat["topic_summary"],
        base_reward_seconds=pol["base_reward_seconds"],
        level_factor=level, novelty_factor=novelty,
        max_reward_seconds=int(R.max_possible_reward(
            base_seconds=pol["base_reward_seconds"], questions=len(rows),
            essay_ratio=float(pol["essay_ratio"]),
            level_factor_=level, novelty_factor_=novelty,
        )),
        ready_count=qs["ready_count"], total_count=qs["requested_count"],
        status=qs["status"], questions=questions,
    )


@router.get("/quizzes/{session_id}", response_model=S.QuizOut)
async def get_quiz(session_id: uuid.UUID, db: Conn, me: Me):
    ses = await _load(db, session_id)
    await authorize_subject(db, me, ses["subject_id"])

    qs = (
        await db.execute(
            select(T.question_sets).where(T.question_sets.c.id == ses["question_set_id"])
        )
    ).mappings().one()
    mat = (
        await db.execute(select(T.materials).where(T.materials.c.id == qs["material_id"]))
    ).mappings().one()
    rows = {
        str(r["id"]): r for r in (
            await db.execute(
                select(T.questions).where(T.questions.c.question_set_id == qs["id"])
            )
        ).mappings().all()
    }

    order = list(ses["question_order"])
    perms = dict(ses["option_permutation"])
    for qid, r in rows.items():
        if qid not in order:
            order.append(qid)
            if r["qtype"] == "mcq" and r["options"]:
                perms[qid] = random.sample(range(len(r["options"])), len(r["options"]))
    if len(order) != len(ses["question_order"]):
        await db.execute(
            T.quiz_sessions.update().where(T.quiz_sessions.c.id == session_id)
            .values(question_order=order, option_permutation=perms)
        )

    return S.QuizOut(
        session_id=session_id, material_id=qs["material_id"], title=mat["topic_summary"],
        base_reward_seconds=ses["base_reward_seconds"],
        level_factor=float(ses["level_factor"]), novelty_factor=float(ses["novelty_factor"]),
        max_reward_seconds=int(R.max_possible_reward(
            base_seconds=ses["base_reward_seconds"], questions=len(order), essay_ratio=0.0,
            level_factor_=float(ses["level_factor"]), novelty_factor_=float(ses["novelty_factor"]),
        )),
        ready_count=qs["ready_count"], total_count=qs["requested_count"],
        status=qs["status"],
        answered_ids=[
            r[0] for r in (
                await db.execute(
                    select(T.quiz_answers.c.question_id)
                    .where(T.quiz_answers.c.session_id == session_id)
                )
            ).all()
        ],
        questions=[_public(rows[q], perms.get(q, [])) for q in order if q in rows],
    )


@router.post("/quizzes/{session_id}/answers", response_model=S.AnswerSavedOut)
async def answer(session_id: uuid.UUID, body: S.AnswerIn, db: Conn, me: Me):
    ses = await _load(db, session_id)
    await authorize_subject(db, me, ses["subject_id"])
    if me.is_parent:
        raise Forbidden("Sesi dikerjakan oleh pemilik materi.")
    if ses["status"] != "open":
        raise Conflict("Sesi ini sudah dikumpulkan.", code="session_closed")

    q = (
        await db.execute(select(T.questions).where(T.questions.c.id == body.question_id))
    ).mappings().first()
    if not q or q["question_set_id"] != ses["question_set_id"]:
        raise NotFound("Soal tidak ada di sesi ini.")

    if q["qtype"] == "mcq" and body.chosen_index is None:
        raise Invalid("Pilih salah satu jawaban dulu.")
    if q["qtype"] == "essay" and not (body.essay_text or "").strip():
        raise Invalid("Tulis jawabanmu dulu.")

    values = {
        "session_id": session_id,
        "question_id": q["id"],
        "chosen_index": body.chosen_index,
        "essay_text": body.essay_text,
        "answered_at": now(),
    }
    await db.execute(
        pg_insert(T.quiz_answers).values(**values).on_conflict_do_update(
            index_elements=[T.quiz_answers.c.session_id, T.quiz_answers.c.question_id],
            set_={k: values[k] for k in ("chosen_index", "essay_text", "answered_at")},
        )
    )

    answered = (
        await db.execute(
            select(func.count()).select_from(T.quiz_answers)
            .where(T.quiz_answers.c.session_id == session_id)
        )
    ).scalar_one()
    return S.AnswerSavedOut(
        question_id=q["id"], answered_count=int(answered),
        total_count=len(list(ses["question_order"])),
    )


@router.post("/quizzes/{session_id}/submit", response_model=S.ReceiptOut)
async def submit(session_id: uuid.UUID, db: Conn, me: Me):
    ses = await _load(db, session_id)
    await authorize_subject(db, me, ses["subject_id"])
    if me.is_parent:
        raise Forbidden("Sesi dikumpulkan oleh pemilik materi.")
    if ses["status"] != "open":
        raise Conflict("Sesi ini sudah dikumpulkan.", code="session_closed")

    qs = (
        await db.execute(
            select(T.question_sets).where(T.question_sets.c.id == ses["question_set_id"])
        )
    ).mappings().one()
    mat = (
        await db.execute(select(T.materials).where(T.materials.c.id == qs["material_id"]))
    ).mappings().one()
    questions = {
        str(r["id"]): r for r in (
            await db.execute(
                select(T.questions).where(T.questions.c.question_set_id == qs["id"])
                .order_by(T.questions.c.ordinal)
            )
        ).mappings().all()
    }
    answers = {
        str(a["question_id"]): a for a in (
            await db.execute(
                select(T.quiz_answers).where(T.quiz_answers.c.session_id == session_id)
            )
        ).mappings().all()
    }

    order = list(ses["question_order"])
    missing = [qid for qid in order if qid in questions and qid not in answers]
    if missing:
        raise Conflict(
            f"Masih ada {len(missing)} soal yang belum dijawab.", code="incomplete_session"
        )

    lf, nf = float(ses["level_factor"]), float(ses["novelty_factor"])
    base = ses["base_reward_seconds"]
    marks: dict[str, dict] = {}

    for qid in order:
        q = questions.get(qid)
        if not q:
            continue
        a = answers[qid]
        if q["qtype"] == "mcq":
            perm = list(ses["option_permutation"].get(qid, []))
            picked = a["chosen_index"]
            real = perm[picked] if (picked is not None and perm) else picked
            ok = grading.grade_mcq(chosen_index=real, correct_index=q["correct_index"])
            mark = {
                "is_correct": ok, "score": None, "evaluator_notes": None,
                "injection_flag": False,
                "reward_seconds": R.question_reward(
                    base_seconds=base, difficulty=q["difficulty"], qtype="mcq",
                    level_factor_=lf, novelty_factor_=nf, correct=ok,
                ),
            }
        else:
            verdict = await grading.grade_essay(
                stem=q["stem"], rubric=list(q["rubric"] or []),
                reference_answer=q["reference_answer"] or "", answer=a["essay_text"] or "",
            )
            mark = {
                "is_correct": verdict.passed, "score": verdict.score,
                "evaluator_notes": verdict.notes, "injection_flag": verdict.injection_flag,
                "reward_seconds": R.question_reward(
                    base_seconds=base, difficulty=q["difficulty"], qtype="essay",
                    level_factor_=lf, novelty_factor_=nf, score=verdict.rewardable_score,
                ),
            }
            if verdict.injection_flag:
                await db.execute(
                    T.guardian_events.insert().values(
                        subject_id=ses["subject_id"], event_type="essay_injection_attempt",
                        payload={"session_id": str(session_id), "question_id": qid},
                    )
                )
        marks[qid] = mark
        await db.execute(
            T.quiz_answers.update().where(
                T.quiz_answers.c.session_id == session_id,
                T.quiz_answers.c.question_id == q["id"],
            ).values(**mark)
        )

    rows: list[S.ReceiptRow] = []
    subtotal = 0.0
    correct = hard = essay_passed = 0

    for n, qid in enumerate(order, start=1):
        q = questions.get(qid)
        if not q:
            continue
        mult = R.DIFFICULTY_FACTOR[q["difficulty"]] * R.TYPE_FACTOR[q["qtype"]]
        label = f"{n} · {'esai' if q['qtype'] == 'essay' else 'PG'} · {q['difficulty']}"
        a = marks[qid]

        if a["injection_flag"]:
            rows.append(S.ReceiptRow(ordinal=n, label=label, qtype=q["qtype"],
                                     difficulty=q["difficulty"], multiplier=mult,
                                     reward_seconds=0.0, voided=True,
                                     void_reason="ditandai",
                                     explanation=q["explanation"]))
            continue

        earned = float(a["reward_seconds"] or 0)
        if earned <= 0:
            rows.append(S.ReceiptRow(ordinal=n, label=label, qtype=q["qtype"],
                                     difficulty=q["difficulty"], multiplier=mult,
                                     reward_seconds=0.0, voided=True,
                                     void_reason="salah",
                                     score=float(a["score"]) if a["score"] is not None else None,
                                     explanation=q["explanation"]))
            continue

        pre = earned / (lf * nf) if lf * nf else earned
        subtotal += pre
        correct += 1
        if q["difficulty"] == "sulit":
            hard += 1
        if q["qtype"] == "essay":
            essay_passed += 1
        rows.append(S.ReceiptRow(
            ordinal=n, label=label, qtype=q["qtype"], difficulty=q["difficulty"],
            multiplier=mult, reward_seconds=round(pre, 2),
            score=float(a["score"]) if a["score"] is not None else None,
            explanation=q["explanation"],
        ))

    gross = subtotal * lf * nf
    settlement = await L.credit_reward(
        db, subject_id=ses["subject_id"], gross_seconds=gross,
        note=mat["topic_summary"] or mat["original_name"] or "Sesi belajar",
        ref_id=session_id,
    )

    st = await L.standing(db, ses["subject_id"])
    badges = await PR.record_session(
        db, subject_id=ses["subject_id"], day=st.day, correct=correct, hard=hard,
        essay_passed=essay_passed, from_photo=(mat["source_type"] or "").startswith("image/"),
        cross_language=(mat["detected_language"] or "id") != "id",
        perfect=correct == len(rows) and correct > 0,
    )

    await db.execute(
        T.quiz_sessions.update().where(T.quiz_sessions.c.id == session_id).values(
            status="submitted", submitted_at=now(), correct_count=correct,
            reward_seconds=settlement.to_balance, overflow_points=settlement.overflow_points,
        )
    )
    await db.execute(
        T.materials.update().where(T.materials.c.id == mat["id"]).values(last_studied_at=now())
    )

    prog = (
        await db.execute(
            select(T.progress.c.streak_current).where(T.progress.c.subject_id == ses["subject_id"])
        )
    ).scalar() or 0

    return S.ReceiptOut(
        session_id=session_id,
        title=mat["topic_summary"] or mat["original_name"],
        base_reward_seconds=ses["base_reward_seconds"],
        rows=rows, subtotal_seconds=round(subtotal, 2),
        level_factor=lf,
        level_note="setara" if lf == 1.0 else "satu tingkat di bawah",
        novelty_factor=nf,
        novelty_note={1.0: "materi baru", 0.6: "pengulangan sebagian"}.get(nf, "materi yang sama"),
        gross_seconds=round(gross, 2),
        credited_seconds=settlement.to_balance,
        overflow_points=settlement.overflow_points,
        balance_seconds=st.balance, ceiling_seconds=st.ceiling,
        correct_count=correct, question_count=len(rows),
        streak_current=int(prog), new_badges=[b.name for b in badges],
    )


@router.get("/subjects/{subject_id}/offline-bank", response_model=list[S.OfflineQuestionOut])
async def offline_bank(subject_id: uuid.UUID, db: Conn, me: Me, limit: int = 20):
    await authorize_subject(db, me, subject_id)
    if not me.device_id:
        raise Forbidden("Bank luring hanya untuk perangkat berpasangan.")

    dev = (
        await db.execute(select(T.devices).where(T.devices.c.id == me.device_id))
    ).mappings().one()

    rows = (
        await db.execute(
            select(T.questions)
            .join(T.question_sets, T.question_sets.c.id == T.questions.c.question_set_id)
            .join(T.materials, T.materials.c.id == T.question_sets.c.material_id)
            .where(
                T.materials.c.subject_id == subject_id,
                T.materials.c.deleted_at.is_(None),
                T.questions.c.qtype == "mcq",
            )
            .order_by(T.question_sets.c.generated_at.desc())
            .limit(min(limit, 60))
        )
    ).mappings().all()

    from app.security import answer_hmac
    return [
        S.OfflineQuestionOut(
            id=r["id"], qtype="mcq", stem=r["stem"], options=list(r["options"] or []),
            difficulty=r["difficulty"], source_excerpt=r["source_excerpt"],
            answer_hmac=answer_hmac(
                question_id=str(r["id"]), correct_index=r["correct_index"],
                device_secret=dev["device_secret_hash"],
            ),
        )
        for r in rows
    ]
