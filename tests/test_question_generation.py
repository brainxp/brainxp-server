import inspect
import uuid

import pytest
from pydantic import ValidationError

from app import schemas as S
from app.services import generation as G
from app.services import llm as L
from app.services import rules as R

MAX_QUESTIONS = 10
CHARS_PER_TOKEN = 3


def worst_case_chars(mcq: int, essays: int) -> int:
    per_mcq = L.STEM_MAX + 4 * L.OPTION_MAX + L.EXCERPT_MAX + L.EXPLANATION_MAX
    per_essay = (
        L.STEM_MAX + L.EXCERPT_MAX + L.EXPLANATION_MAX + L.REFERENCE_MAX
        + 3 * (L.CRITERION_MAX + L.INDICATOR_MAX)
    )
    return mcq * per_mcq + essays * per_essay


def a_question(stem: str) -> L.GeneratedQuestion:
    return L.GeneratedQuestion(
        qtype="mcq", stem=stem, options=["A", "B", "C", "D"], correct_index=0,
        source_excerpt="cuplikan materi", explanation="pembahasan singkat.",
        difficulty="sedang", bloom_level="understand",
    )


def test_a_session_cannot_ask_for_more_than_the_budgeted_maximum():
    S.PolicyIn(questions_per_session=MAX_QUESTIONS)
    with pytest.raises(ValidationError):
        S.PolicyIn(questions_per_session=MAX_QUESTIONS + 1)


def test_the_token_budget_covers_a_session_of_nothing_but_essays():
    needed = worst_case_chars(0, MAX_QUESTIONS) // CHARS_PER_TOKEN
    assert L.generation_token_budget(MAX_QUESTIONS) > needed, (
        "essay_ratio of 1.0 on a ten question policy is the worst case, and one call "
        "for the whole session now carries all of it; a reply cut off at max_tokens "
        "fails to parse and the child ends up with no questions at all"
    )


def test_the_token_budget_covers_the_usual_mix():
    mcq, essays = R.session_mix(MAX_QUESTIONS, 0.2)
    needed = worst_case_chars(mcq, essays) // CHARS_PER_TOKEN
    assert L.generation_token_budget(MAX_QUESTIONS) > needed


def test_the_token_budget_grows_with_the_number_of_questions():
    assert L.generation_token_budget(MAX_QUESTIONS) > L.generation_token_budget(3), (
        "a fixed ceiling was safe while a call carried at most seven questions; it "
        "has to follow the request now that one call carries the session"
    )


def test_the_whole_session_is_generated_in_one_call():
    source = inspect.getsource(G.run)
    assert source.count("generate_questions") == 1, (
        "two calls cannot spread difficulty and Bloom level across the set, because "
        "the first one does not know what the second will write and the second only "
        "receives the stems to avoid"
    )
    assert "priority_batch" not in source


def test_the_saved_rows_are_numbered_from_zero_without_gaps():
    rows = G._rows_for(uuid.uuid4(), [a_question(f"Soal {i}?") for i in range(4)])
    assert [r["ordinal"] for r in rows] == [0, 1, 2, 3], (
        "the set is read back with order_by(ordinal) and the number is shown to the "
        "child, so it has to be contiguous from zero"
    )


def test_the_saved_rows_no_longer_carry_a_batch_number():
    rows = G._rows_for(uuid.uuid4(), [a_question("Soal?")])
    assert "batch_index" not in rows[0], (
        "one call means one batch, so the column keeps its default rather than the "
        "caller passing a number that is always zero"
    )


async def test_a_stub_provider_returns_the_whole_session_at_once():
    batch = await L.StubProvider().generate_questions(
        att=L.Attachment(media_type="text/plain", data=b"materi"),
        count=MAX_QUESTIONS, essays=2, academic_level="smp", language="id",
    )
    assert len(batch.questions) == MAX_QUESTIONS
    assert sum(1 for q in batch.questions if q.qtype == "essay") == 2
