from app.routers.policies import _is_weakening

BASE = {
    "questions_per_session": 10,
    "base_reward_seconds": 120,
    "daily_caps": [3600, 3600, 3600, 3600, 3600, 3600, 3600],
    "daily_grants": [0, 0, 0, 0, 0, 0, 0],
    "idle_days_allowed": 2,
    "essay_ratio": 0.2,
    "locked_apps": ["ml", "tt"],
}


def test_raising_the_daily_cap_is_a_loosening():
    assert _is_weakening(BASE, {"daily_caps": [3600, 3600, 3600, 3600, 3600, 7200, 7200]})


def test_lowering_the_daily_cap_is_a_tightening():
    assert not _is_weakening(BASE, {"daily_caps": [1800] * 7})


def test_granting_more_idle_days_is_a_loosening():
    assert _is_weakening(BASE, {"idle_days_allowed": 4})


def test_granting_fewer_idle_days_is_a_tightening():
    assert not _is_weakening(BASE, {"idle_days_allowed": 0})


def test_raising_the_reward_per_question_is_a_loosening():
    assert _is_weakening(BASE, {"base_reward_seconds": 300})


def test_lowering_the_reward_per_question_is_a_tightening():
    assert not _is_weakening(BASE, {"base_reward_seconds": 60})


def test_asking_fewer_questions_is_a_loosening():
    assert _is_weakening(BASE, {"questions_per_session": 5})


def test_asking_more_questions_is_a_tightening():
    assert not _is_weakening(BASE, {"questions_per_session": 20})


def test_taking_an_app_off_the_lock_list_is_a_loosening():
    assert _is_weakening(BASE, {"locked_apps": ["ml"]})


def test_adding_an_app_to_the_lock_list_is_a_tightening():
    assert not _is_weakening(BASE, {"locked_apps": ["ml", "tt", "ig"]})


def test_swapping_one_app_for_another_still_counts_as_loosening():
    assert _is_weakening(BASE, {"locked_apps": ["ml", "ig"]})


def test_shrinking_the_essay_ratio_is_a_loosening():
    assert _is_weakening(BASE, {"essay_ratio": 0.0})


def test_an_empty_change_is_not_a_loosening():
    assert not _is_weakening(BASE, {})
    assert not _is_weakening(BASE, {"daily_cap_seconds": None})


def test_loosening_a_single_day_still_counts():
    saturday_up = [3600, 1800, 1800, 1800, 1800, 7200, 1800]
    assert _is_weakening(BASE, {"daily_caps": saturday_up}), (
        "raising one day is still a loosening even when the other days tighten"
    )


def test_lowering_every_day_is_a_tightening():
    assert not _is_weakening(BASE, {"daily_caps": [1800] * 7})


def test_raising_the_weekend_daily_grant_is_a_loosening():
    assert _is_weakening(BASE, {"daily_grants": [0, 0, 0, 0, 0, 1800, 1800]})
