from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.services import rules as R

JKT = ZoneInfo("Asia/Jakarta")


@pytest.mark.parametrize(
    "declared,assessed,expected",
    [
        ("smp", "smp", 1.0),
        ("smp", "sma", 1.0),
        ("sd", "profesional", 1.0),
        ("sma", "smp", 0.0),
        ("sma", "sd", 0.0),
        ("kuliah", "sd", 0.0),
    ],
)
def test_level_factor(declared, assessed, expected):
    assert R.level_factor(declared, assessed) == expected


def test_gate_rejects_material_two_levels_below():
    out = R.evaluate_gate(
        declared_level="sma", assessed_level="sd",
        concept_density=0.5, is_study_material=True, times_seen=0,
    )
    assert not out.accepted
    assert out.reject_reason == R.RejectReason.LEVEL_TOO_LOW


def test_gate_rejects_material_one_level_below():
    out = R.evaluate_gate(
        declared_level="sma", assessed_level="smp",
        concept_density=0.5, is_study_material=True, times_seen=0,
    )
    assert not out.accepted, (
        "material below the declared level tests nothing, however close the gap"
    )
    assert out.reject_reason == R.RejectReason.LEVEL_TOO_LOW


def test_gate_accepts_material_above_the_level_at_full_reward():
    out = R.evaluate_gate(
        declared_level="sma", assessed_level="kuliah",
        concept_density=0.5, is_study_material=True, times_seen=0,
    )
    assert out.accepted
    assert out.level_factor == 1.0, "reaching for harder material must not be punished"


def test_gate_rejects_material_that_is_too_thin():
    out = R.evaluate_gate(
        declared_level="smp", assessed_level="smp",
        concept_density=0.05, is_study_material=True, times_seen=0,
    )
    assert not out.accepted
    assert out.reject_reason == R.RejectReason.TOO_THIN


def test_novelty_decay():
    assert R.novelty_factor(0) == 1.0
    assert R.novelty_factor(1) == 0.6
    assert R.novelty_factor(5) == 0.3


def test_restudying_the_same_material_shrinks_the_reward():
    out = R.evaluate_gate(
        declared_level="sma", assessed_level="sma",
        concept_density=0.4, is_study_material=True, times_seen=2,
    )
    assert out.combined == pytest.approx(0.3)


def test_bloom_floor_for_sma_needs_mostly_analytical_questions():
    recall_only = ["remember"] * 10
    mixed = ["apply"] * 6 + ["remember"] * 4
    assert not R.bloom_floor_met(recall_only, "sma")
    assert R.bloom_floor_met(mixed, "sma")
    assert R.bloom_floor_met(recall_only, "sd")


def test_multiple_choice_reward_follows_difficulty():
    kw = {"base_seconds": 120, "qtype": "mcq", "level_factor_": 1.0,
          "novelty_factor_": 1.0, "correct": True}
    assert R.question_reward(difficulty="mudah", **kw) == pytest.approx(72.0)
    assert R.question_reward(difficulty="sedang", **kw) == pytest.approx(120.0)
    assert R.question_reward(difficulty="sulit", **kw) == pytest.approx(192.0)


def test_a_wrong_answer_earns_nothing():
    assert R.question_reward(
        base_seconds=120, difficulty="sulit", qtype="mcq",
        level_factor_=1.0, novelty_factor_=1.0, correct=False,
    ) == 0.0


def test_an_essay_is_worth_more_and_scales_with_the_score():
    reward = R.question_reward(
        base_seconds=120, difficulty="sulit", qtype="essay",
        level_factor_=1.0, novelty_factor_=1.0, score=82,
    )
    assert reward == pytest.approx(120 * 1.6 * 1.8 * 0.82)


def test_an_essay_below_the_threshold_earns_nothing():
    assert R.question_reward(
        base_seconds=120, difficulty="sulit", qtype="essay",
        level_factor_=1.0, novelty_factor_=1.0, score=59,
    ) == 0.0


def test_a_full_session_matches_the_hand_calculation():
    base = 120
    total = sum(
        R.question_reward(base_seconds=base, difficulty=d, qtype="mcq",
                          level_factor_=1.0, novelty_factor_=1.0, correct=True)
        for d in ["sedang", "mudah", "sedang", "sulit", "sedang", "mudah", "sulit", "sedang"]
    )
    total += R.question_reward(base_seconds=base, difficulty="sulit", qtype="essay",
                               level_factor_=1.0, novelty_factor_=1.0, score=82)
    assert total == pytest.approx(1008 + 283.392)


def test_session_ceiling():
    ceiling = R.max_possible_reward(base_seconds=120, questions=10, essay_ratio=0.2)
    assert ceiling == pytest.approx(8 * 192 + 2 * 192 * 1.8)


def test_the_daily_cap_follows_the_day_of_the_week():
    caps = [3600, 3600, 3600, 3600, 3600, 7200, 7200]
    monday = date(2026, 9, 7)
    saturday = date(2026, 9, 12)
    sunday = date(2026, 9, 13)
    assert monday.weekday() == 0
    assert R.cap_for(monday, caps) == 3600
    assert R.cap_for(saturday, caps) == 7200
    assert R.cap_for(sunday, caps) == 7200


def test_the_daily_grant_follows_the_day_too():
    grants = [0, 0, 0, 0, 0, 1800, 1800]
    assert R.grant_for(date(2026, 9, 7), grants) == 0
    assert R.grant_for(date(2026, 9, 12), grants) == 1800


def test_the_balance_locks_once_the_idle_allowance_runs_out():
    today = date(2026, 9, 10)
    assert not R.locked_by_idle(last_study_day=today, today=today, allowed=2)
    assert not R.locked_by_idle(last_study_day=date(2026, 9, 8), today=today, allowed=2)
    assert R.locked_by_idle(last_study_day=date(2026, 9, 7), today=today, allowed=2)


def test_a_zero_allowance_means_studying_every_day():
    today = date(2026, 9, 10)
    assert not R.locked_by_idle(last_study_day=today, today=today, allowed=0)
    assert R.locked_by_idle(last_study_day=date(2026, 9, 9), today=today, allowed=0)


def test_someone_who_never_studied_is_not_locked():
    assert not R.locked_by_idle(last_study_day=None, today=date(2026, 9, 10), allowed=0)


def test_an_idle_lock_does_not_eat_the_balance():
    state = {"balance": 5400, "daily_cap": 3600, "spent_today": 0}
    assert R.playable_seconds(**state, idle_locked=True) == 0
    assert R.playable_seconds(**state, idle_locked=False) == 3600
    assert R.block_reason(**state, idle_locked=True) == R.BlockReason.IDLE


def test_an_empty_balance_reads_as_empty_not_locked():
    assert R.block_reason(
        balance=0, daily_cap=3600, spent_today=0, idle_locked=True
    ) == R.BlockReason.NO_BALANCE


def test_two_in_the_morning_still_counts_as_the_previous_day():
    late_night = datetime(2026, 9, 3, 23, 40, tzinfo=JKT)
    small_hours = datetime(2026, 9, 4, 2, 10, tzinfo=JKT)
    assert R.day_key(late_night, reset_hour=5) == R.day_key(small_hours, reset_hour=5)
    assert R.day_key(small_hours, reset_hour=5) == date(2026, 9, 3)


def test_midnight_splits_the_day_when_the_reset_hour_is_zero():
    late_night = datetime(2026, 9, 3, 23, 40, tzinfo=JKT)
    small_hours = datetime(2026, 9, 4, 0, 10, tzinfo=JKT)
    assert R.day_key(late_night, reset_hour=0) != R.day_key(small_hours, reset_hour=0)


def test_time_left_until_the_day_rolls_over():
    at = datetime(2026, 9, 3, 22, 0, tzinfo=JKT)
    assert R.seconds_until_reset(at, reset_hour=5) == 7 * 3600


def test_the_daily_cap_binds_even_on_a_large_balance():
    assert R.playable_seconds(balance=10800, daily_cap=3600, spent_today=3000) == 600


def test_a_small_balance_binds_even_under_a_loose_cap():
    assert R.playable_seconds(balance=300, daily_cap=3600, spent_today=0) == 300


def test_the_two_reasons_for_blocking_are_told_apart():
    assert R.block_reason(balance=0, daily_cap=3600, spent_today=0) == R.BlockReason.NO_BALANCE
    assert R.block_reason(balance=4200, daily_cap=3600, spent_today=3600) == R.BlockReason.DAILY_CAP
    assert R.block_reason(balance=4200, daily_cap=3600, spent_today=600) == R.BlockReason.NONE


def test_a_streak_grows_on_consecutive_days():
    before = R.StreakState(3, 5, 0, date(2026, 9, 2))
    after = R.advance_streak(before, date(2026, 9, 3))
    assert after.current == 4


def test_a_second_session_on_the_same_day_does_not_extend_the_streak():
    state = R.StreakState(3, 5, 0, date(2026, 9, 3))
    assert R.advance_streak(state, date(2026, 9, 3)) == state


def test_a_freeze_token_saves_one_missed_day():
    before = R.StreakState(9, 9, 1, date(2026, 9, 1))
    after = R.advance_streak(before, date(2026, 9, 3))
    assert after.current == 10
    assert after.freeze_tokens == 0


def test_without_a_freeze_token_the_streak_breaks():
    before = R.StreakState(9, 9, 0, date(2026, 9, 1))
    after = R.advance_streak(before, date(2026, 9, 3))
    assert after.current == 1
    assert after.longest == 9


def test_a_freeze_token_arrives_every_seven_days_and_caps_at_two():
    state = R.StreakState(6, 6, 0, date(2026, 9, 2))
    state = R.advance_streak(state, date(2026, 9, 3))
    assert (state.current, state.freeze_tokens) == (7, 1)
    for day in range(4, 11):
        state = R.advance_streak(state, date(2026, 9, day))
    assert state.current == 14
    assert state.freeze_tokens == 2


def test_the_question_split_follows_the_essay_ratio():
    assert R.session_mix(10, 0.2) == (8, 2)
    assert R.session_mix(10, 0.0) == (10, 0)
    assert R.session_mix(10, 1.0) == (0, 10)
    assert R.session_mix(5, 0.4) == (3, 2)


def test_the_stale_guardian_block_reason_has_a_value_of_its_own():
    assert R.BlockReason.GUARDIAN_STALE == "guardian_stale"
    assert R.BlockReason.GUARDIAN_STALE not in (
        R.BlockReason.NO_BALANCE, R.BlockReason.DAILY_CAP, R.BlockReason.NONE
    )


def test_an_intact_balance_is_never_reported_as_empty():
    assert R.block_reason(balance=1740, daily_cap=3600, spent_today=60) == R.BlockReason.NONE


def test_the_worker_waits_long_enough_for_the_material_row():
    from app.services import generation as G

    assert G.VISIBILITY_TRIES * G.VISIBILITY_PAUSE >= 3.0, (
        "a large upload takes seconds to commit, so the wait window has to outlast "
        "it or the worker gives up first"
    )


def test_a_question_cannot_become_a_container_for_long_text():
    from app.services import llm as L

    assert L.EXPLANATION_MAX <= 900, "a long explanation is somewhere to smuggle code"
    assert L.STEM_MAX <= 800
    assert L.OPTION_MAX <= 400
    assert L.REFERENCE_MAX <= 2000
    assert L.CRITERION_MAX <= 400
    assert L.INDICATOR_MAX <= 400
    assert L.INDICATOR_MAX >= 250, (
        "rubric indicators written by the model measured up to 229 characters; "
        "a limit below that discards the essay silently"
    )


def test_the_length_limit_does_not_void_the_whole_batch():
    from app.services import llm as L

    long_text = "x" * (L.EXPLANATION_MAX + 500)
    L.GeneratedQuestion(
        qtype="mcq", stem="Apa?", options=["A", "B", "C", "D"], correct_index=0,
        source_excerpt="cuplikan", explanation=long_text,
        difficulty="mudah", bloom_level="understand",
    )


def test_user_material_is_framed_as_data():
    from app.services import llm as L

    assert "MATERI PENGGUNA DIMULAI" in L.MATERIAL_OPENS
    assert "MATERI PENGGUNA SELESAI" in L.MATERIAL_CLOSES
    assert "bukan instruksi" in L.MATERIAL_CLOSES
    assert "kode program" in L.MATERIAL_CLOSES
    assert "bukan bahan belajar" not in L.MATERIAL_CLOSES, (
        "the boundary reminder must not steer the gate verdict; it makes clean "
        "material get rejected too"
    )


def test_the_expensive_paths_have_rate_limits():
    from app.services import ratelimit as RL

    for window in (RL.REGISTER_PER_IP, RL.UPLOAD_PER_IP, RL.UPLOAD_GLOBAL, RL.SUBMIT_PER_SUBJECT):
        assert window.limit > 0 and window.seconds > 0

    assert RL.REGISTER_PER_IP.limit >= 3, "one family may well register more than once"
    assert RL.UPLOAD_PER_IP.limit >= 20, "one household shares one IP"
    assert RL.UPLOAD_PER_IP.limit < RL.UPLOAD_GLOBAL.limit


def test_the_length_limit_is_not_held_over_the_model():
    from app.services import llm as L

    prompt = " ".join(L.GEN_SYSTEM.split())
    assert "dibuang" not in prompt, (
        "telling the model questions get discarded makes it avoid essays, which "
        "need longer rubrics and reference answers"
    )
    assert "Esai tetap dibuat" in prompt
    assert "Nilai berkasnya" not in L.MATERIAL_CLOSES, (
        "judging the file is the gate's instruction, not the question writer's"
    )
