import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args

import pytest

from app import question_reports as QR
from app import schemas as S
from app.errors import AppError
from app.routers import quizzes
from tests.conftest import Recorder, rendered

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


class Child:
    role = "child"
    user_id = None
    device_id = None
    is_parent = False
    is_child = True

    def __init__(self, subject_id):
        self.subject_id = subject_id


@pytest.fixture
def session():
    return {
        "id": uuid.uuid4(),
        "subject_id": uuid.uuid4(),
        "question_set_id": uuid.uuid4(),
        "status": "submitted",
    }


@pytest.fixture(autouse=True)
def any_subject_is_yours(monkeypatch):
    async def allow(db, me, subject_id):
        return {"id": subject_id, "user_id": None}

    monkeypatch.setattr(quizzes, "authorize_subject", allow)


def database(session, question_set_id=None):
    return Recorder({
        ("select", "quiz_sessions"): [session],
        ("select", "questions"): [question_set_id or session["question_set_id"]],
        ("insert", "question_reports"): [7],
    })


def report(reason="kunci_salah", note=None, question_id=None) -> S.QuestionReportIn:
    return S.QuestionReportIn(question_id=question_id or uuid.uuid4(), reason=reason, note=note)


async def test_a_report_on_a_graded_session_is_recorded(session):
    db = database(session)
    body = report(note="  jawabannya harusnya B  ")

    out = await quizzes.report_question(session["id"], body, db, Child(session["subject_id"]))

    assert out.id == 7 and out.question_id == body.question_id
    stmt, _ = db.only("insert", "question_reports")
    sql = rendered(stmt, literals=True)
    assert "'kunci_salah'" in sql and "'child'" in sql
    assert "'jawabannya harusnya B'" in sql, "the note is stored trimmed"


async def test_reporting_never_touches_the_grade_or_the_balance(session):
    db = database(session)

    await quizzes.report_question(session["id"], report(), db, Child(session["subject_id"]))

    touched = {table for kind, table in db.trail if kind != "select"}
    assert touched == {"question_reports"}, (
        "a report is only input for the developers; letting it change a mark or "
        "refund time would turn reporting into a way to farm minutes"
    )


async def test_reporting_the_same_question_again_updates_the_one_report(session):
    db = database(session)

    await quizzes.report_question(session["id"], report(), db, Child(session["subject_id"]))

    stmt, _ = db.only("insert", "question_reports")
    sql = rendered(stmt)
    assert "ON CONFLICT (session_id, question_id) DO UPDATE" in sql, (
        "tapping the button twice must not queue the same question twice for review"
    )
    assert "reviewed_at" in sql, "a fresh report reopens one that was already reviewed"


async def test_a_question_from_another_set_is_refused(session):
    db = database(session, question_set_id=uuid.uuid4())

    with pytest.raises(AppError) as refusal:
        await quizzes.report_question(session["id"], report(), db, Child(session["subject_id"]))

    assert refusal.value.status_code == 404
    assert ("insert", "question_reports") not in db.trail


async def test_other_needs_a_note(session):
    db = database(session)

    with pytest.raises(AppError) as refusal:
        await quizzes.report_question(
            session["id"], report(reason="lainnya", note="   "), db, Child(session["subject_id"])
        )

    assert refusal.value.status_code == 422, (
        "'other' with no words says nothing a developer can act on"
    )
    assert ("insert", "question_reports") not in db.trail


def test_the_reasons_match_the_database_check():
    sql = next(MIGRATIONS.glob("*_create_question_reports.up.sql")).read_text()
    allowed = set(re.findall(r"'(\w+)'", sql.split("CHECK", 1)[1].split(")", 1)[0]))
    assert allowed == set(get_args(S.ReportReason))


def row(**overrides):
    question_id = uuid.uuid4()
    base = {
        "id": 3, "session_id": uuid.uuid4(), "question_id": question_id,
        "reason": "kunci_salah", "note": None, "reporter_role": "child",
        "updated_at": datetime(2026, 10, 1, 9, 30, tzinfo=UTC), "reviewed_at": None,
        "qtype": "mcq", "difficulty": "sedang", "stem": "2 + 2 = ?",
        "options": ["3", "4", "5", "22"], "correct_index": 1,
        "reference_answer": None, "rubric": None, "explanation": None,
        "source_excerpt": "dua tambah dua", "topic_summary": "Penjumlahan",
        "option_permutation": {str(question_id): [3, 2, 1, 0]},
        "chosen_index": 2, "essay_text": None, "is_correct": True, "score": None,
        "evaluator_notes": None,
    }
    return base | overrides


def test_the_review_shows_the_option_that_was_actually_picked():
    item = QR.entry(row())

    assert item["chosen_index"] == 1, (
        "the stored index is the shuffled position on screen; the review has to "
        "translate it back or every picked answer looks wrong"
    )
    assert "B. 4   <- key, picked" in QR.render(item)


def test_an_unanswered_question_shows_no_pick():
    item = QR.entry(row(chosen_index=None, is_correct=None))

    assert item["chosen_index"] is None
    assert "not yet" in QR.render(item)


def test_an_essay_shows_the_answer_beside_the_reference():
    item = QR.entry(row(
        qtype="essay", options=None, correct_index=None, chosen_index=None,
        essay_text="karena gravitasi", reference_answer="gaya tarik bumi", score=40,
    ))

    text = QR.render(item)
    assert "karena gravitasi" in text and "gaya tarik bumi" in text


def test_the_queue_hides_reviewed_reports_unless_asked():
    assert "reviewed_at IS NULL" in rendered(QR.listing(include_reviewed=False, limit=10))
    assert "reviewed_at IS NULL" not in rendered(QR.listing(include_reviewed=True, limit=10))


def test_marking_reviewed_keeps_the_first_review_time():
    sql = rendered(QR.mark_reviewed([1, 2]))
    assert "reviewed_at IS NULL" in sql
