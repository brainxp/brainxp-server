from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

DIFFICULTY_FACTOR: dict[str, float] = {"mudah": 0.6, "sedang": 1.0, "sulit": 1.6}
TYPE_FACTOR: dict[str, float] = {"mcq": 1.0, "essay": 1.8}

ESSAY_PASS_SCORE = 60

LEVEL_ORDER: list[str] = ["sd", "smp", "sma", "kuliah", "profesional"]

BLOOM_HIGHER = {"apply", "analyze"}
BLOOM_FLOOR: dict[str, float] = {"sd": 0.0, "smp": 0.3, "sma": 0.6, "kuliah": 0.6, "profesional": 0.6}

MIN_CONCEPT_DENSITY = 0.20


class RejectReason:
    LEVEL_TOO_LOW = "level_too_low"
    TOO_THIN = "too_thin"
    NOT_STUDY_MATERIAL = "not_study_material"


@dataclass(frozen=True)
class GateOutcome:
    accepted: bool
    level_factor: float
    novelty_factor: float
    times_seen: int
    reject_reason: str | None = None
    note: str = ""

    @property
    def combined(self) -> float:
        return self.level_factor * self.novelty_factor


def level_index(level: str) -> int:
    try:
        return LEVEL_ORDER.index(level)
    except ValueError:
        return LEVEL_ORDER.index("smp")


def level_factor(declared: str, assessed: str) -> float:
    return 1.0 if level_index(declared) <= level_index(assessed) else 0.0


def novelty_factor(times_seen: int) -> float:
    if times_seen <= 0:
        return 1.0
    if times_seen == 1:
        return 0.6
    return 0.3


def evaluate_gate(
    *,
    declared_level: str,
    assessed_level: str,
    concept_density: float,
    is_study_material: bool,
    times_seen: int,
) -> GateOutcome:
    nov = novelty_factor(times_seen)

    if not is_study_material:
        return GateOutcome(
            False, 0.0, nov, times_seen, RejectReason.NOT_STUDY_MATERIAL,
            "Berkas ini tidak terbaca sebagai materi belajar.",
        )

    if concept_density < MIN_CONCEPT_DENSITY:
        return GateOutcome(
            False, 0.0, nov, times_seen, RejectReason.TOO_THIN,
            "Materinya terlalu tipis untuk menghasilkan soal yang bermakna.",
        )

    lf = level_factor(declared_level, assessed_level)
    if lf == 0.0:
        return GateOutcome(
            False, 0.0, nov, times_seen, RejectReason.LEVEL_TOO_LOW,
            "Materi ini di bawah jenjang yang dipilih, jadi soalnya tidak menguji apa pun.",
        )

    return GateOutcome(True, lf, nov, times_seen, None, "")


def bloom_floor_met(bloom_levels: list[str], academic_level: str) -> bool:
    if not bloom_levels:
        return False
    need = BLOOM_FLOOR.get(academic_level, 0.6)
    if need == 0.0:
        return True
    higher = sum(1 for b in bloom_levels if b in BLOOM_HIGHER)
    return higher / len(bloom_levels) >= need


def score_factor(qtype: str, *, correct: bool = False, score: float | None = None) -> float:
    if qtype == "mcq":
        return 1.0 if correct else 0.0
    if score is None or score < ESSAY_PASS_SCORE:
        return 0.0
    return max(0.0, min(1.0, score / 100.0))


def question_reward(
    *,
    base_seconds: int,
    difficulty: str,
    qtype: str,
    level_factor_: float,
    novelty_factor_: float,
    correct: bool = False,
    score: float | None = None,
) -> float:
    return (
        base_seconds
        * DIFFICULTY_FACTOR.get(difficulty, 1.0)
        * TYPE_FACTOR.get(qtype, 1.0)
        * level_factor_
        * novelty_factor_
        * score_factor(qtype, correct=correct, score=score)
    )


def max_possible_reward(
    *, base_seconds: int, questions: int, essay_ratio: float,
    level_factor_: float = 1.0, novelty_factor_: float = 1.0,
) -> float:
    essays = round(questions * essay_ratio)
    mcqs = max(0, questions - essays)
    hard = DIFFICULTY_FACTOR["sulit"]
    per = base_seconds * hard * level_factor_ * novelty_factor_
    return per * mcqs + per * TYPE_FACTOR["essay"] * essays


WEEK = 7


def cap_for(day: date, caps: Sequence[int]) -> int:
    return int(caps[day.weekday() % WEEK])


def grant_for(day: date, grants: Sequence[int]) -> int:
    return int(grants[day.weekday() % WEEK])


def idle_gap(last_study_day: date | None, today: date) -> int | None:
    return None if last_study_day is None else (today - last_study_day).days


def locked_by_idle(*, last_study_day: date | None, today: date, allowed: int) -> bool:
    gap = idle_gap(last_study_day, today)
    return gap is not None and gap > allowed


def day_key(moment: datetime, *, reset_hour: int, tz: str = "Asia/Jakarta") -> date:
    local = moment.astimezone(ZoneInfo(tz))
    return (local - timedelta(hours=reset_hour)).date()


def seconds_until_reset(moment: datetime, *, reset_hour: int, tz: str = "Asia/Jakarta") -> int:
    local = moment.astimezone(ZoneInfo(tz))
    nxt = local.replace(hour=reset_hour, minute=0, second=0, microsecond=0)
    if nxt <= local:
        nxt += timedelta(days=1)
    return int((nxt - local).total_seconds())


def playable_seconds(
    *, balance: int, daily_cap: int, spent_today: int, idle_locked: bool = False
) -> int:
    if idle_locked:
        return 0
    return max(0, min(balance, daily_cap - spent_today))


class BlockReason:
    NONE = "none"
    NO_BALANCE = "no_balance"
    DAILY_CAP = "daily_cap"
    GUARDIAN_STALE = "guardian_stale"
    IDLE = "idle"


def block_reason(
    *, balance: int, daily_cap: int, spent_today: int, idle_locked: bool = False
) -> str:
    if balance <= 0:
        return BlockReason.NO_BALANCE
    if idle_locked:
        return BlockReason.IDLE
    if daily_cap - spent_today <= 0:
        return BlockReason.DAILY_CAP
    return BlockReason.NONE


@dataclass(frozen=True)
class StreakState:
    current: int
    longest: int
    freeze_tokens: int
    last_study_day: date | None


def advance_streak(state: StreakState, today: date) -> StreakState:
    if state.last_study_day == today:
        return state

    if state.last_study_day is None:
        current, tokens = 1, state.freeze_tokens
    else:
        gap = (today - state.last_study_day).days
        if gap == 1:
            current, tokens = state.current + 1, state.freeze_tokens
        elif gap == 2 and state.freeze_tokens > 0:
            current, tokens = state.current + 1, state.freeze_tokens - 1
        else:
            current, tokens = 1, state.freeze_tokens

    if current % 7 == 0:
        tokens = min(2, tokens + 1)

    return StreakState(current, max(state.longest, current), tokens, today)


def session_mix(questions: int, essay_ratio: float) -> tuple[int, int]:
    essays = max(0, min(questions, round(questions * essay_ratio)))
    return questions - essays, essays


