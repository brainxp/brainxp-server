from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

Level = Literal["sd", "smp", "sma", "kuliah", "profesional"]


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(min_length=1, max_length=80)
    mode: Literal["family", "personal"] = "family"


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    role: str
    user_id: uuid.UUID | None = None
    subject_id: uuid.UUID | None = None
    family_id: uuid.UUID | None = None
    device_secret: str | None = None


class ChildIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    academic_level: Level = "smp"
    question_language: Literal["id", "en"] = "id"


class SelfSubjectIn(BaseModel):
    academic_level: Level = "profesional"
    question_language: Literal["id", "en"] = "id"


class SubjectOut(BaseModel):
    id: uuid.UUID
    display_name: str
    academic_level: str
    kind: str


class BoundDeviceOut(BaseModel):
    platform: str
    model_name: str | None = None
    last_heartbeat_at: datetime | None = None
    paired_at: datetime


class PairingCodeOut(BaseModel):
    bound_device: BoundDeviceOut | None = None
    code: str
    subject_id: uuid.UUID
    expires_at: datetime
    attempts_allowed: int


class PairIn(BaseModel):
    code: str = Field(min_length=6, max_length=6)
    install_binding: str = Field(min_length=8, max_length=200)
    platform: Literal["android", "ios"] = "android"
    model_name: str | None = None


class BindingCheckIn(BaseModel):
    install_binding: str


class BindingCheckOut(BaseModel):
    bound: bool
    subject_name: str | None = None
    family_mode: bool = False


class PolicyOut(BaseModel):
    subject_id: uuid.UUID
    questions_per_session: int
    base_reward_seconds: int
    essay_ratio: float
    academic_level: str
    question_language: str
    daily_caps: list[int]
    daily_grants: list[int]
    idle_days_allowed: int
    day_reset_hour: int
    allowed_upload_methods: list[str]
    locked_apps: list[str]
    pending_weaken_at: datetime | None = None
    pending_weaken_payload: dict | None = None


class PolicyIn(BaseModel):
    questions_per_session: int | None = Field(default=None, ge=1, le=10)
    base_reward_seconds: int | None = Field(default=None, ge=15, le=1800)
    essay_ratio: float | None = Field(default=None, ge=0, le=1)
    academic_level: Level | None = None
    question_language: Literal["id", "en"] | None = None
    daily_caps: list[int] | None = Field(default=None, min_length=7, max_length=7)
    daily_grants: list[int] | None = Field(default=None, min_length=7, max_length=7)
    idle_days_allowed: int | None = Field(default=None, ge=0, le=14)
    day_reset_hour: int | None = Field(default=None, ge=0, le=23)
    allowed_upload_methods: list[Literal["photo", "document"]] | None = None
    locked_apps: list[str] | None = None


class PolicyChangeOut(BaseModel):
    applied: bool
    pending_until: datetime | None = None
    message: str


class StandingOut(BaseModel):
    balance_seconds: int
    playable_seconds: int
    daily_cap_seconds: int
    spent_today_seconds: int
    idle_days: int
    idle_days_allowed: int
    block_reason: Literal["none", "no_balance", "daily_cap", "guardian_stale", "idle"]
    seconds_until_reset: int
    streak_current: int
    freeze_tokens: int


class LedgerEntryOut(BaseModel):
    delta_seconds: int
    entry_type: str
    note: str | None
    occurred_at: datetime


class ConsumptionIn(BaseModel):
    client_event_id: str = Field(min_length=8, max_length=100)
    seconds: int = Field(ge=1, le=86400)
    app_label: str = Field(max_length=80)
    occurred_at: datetime | None = None


class AdjustIn(BaseModel):
    direction: Literal["grant", "redeem"]
    seconds: int = Field(ge=60, le=86400)
    note: str = Field(min_length=3, max_length=200)


class UnfinishedOut(BaseModel):
    session_id: uuid.UUID
    answered: int
    total: int


class MaterialOut(BaseModel):
    id: uuid.UUID
    original_name: str | None
    source_type: str
    status: str
    page_count: int | None = None
    assessed_level: str | None = None
    declared_level: str | None = None
    concept_density: float | None = None
    detected_language: str | None = None
    novelty_score: float | None = None
    gate_verdict: str | None = None
    gate_reason: str | None = None
    topic_summary: str | None = None
    retention_mode: str
    created_at: datetime
    times_studied: int = 0
    question_count: int = 0
    unfinished: UnfinishedOut | None = None


class MaterialAcceptedOut(BaseModel):
    material_id: uuid.UUID
    status: str
    duplicate_of: uuid.UUID | None = None


class RetentionIn(BaseModel):
    retention_mode: Literal["keep", "auto_purge"]


class QuestionPublic(BaseModel):
    id: uuid.UUID
    ordinal: int
    qtype: Literal["mcq", "essay"]
    stem: str
    options: list[str] | None = None
    difficulty: str
    bloom_level: str
    source_excerpt: str
    rubric_criteria: list[str] | None = None
    type_factor: float
    difficulty_factor: float


class QuizStartIn(BaseModel):
    material_id: uuid.UUID


class AnswerStateOut(BaseModel):
    question_id: uuid.UUID
    chosen_index: int | None = None
    essay_text: str | None = None


class QuizOut(BaseModel):
    session_id: uuid.UUID
    material_id: uuid.UUID
    title: str | None
    base_reward_seconds: int
    level_factor: float
    novelty_factor: float
    max_reward_seconds: int
    ready_count: int
    total_count: int
    status: str
    answered_ids: list[uuid.UUID] = Field(default_factory=list)
    answers: list[AnswerStateOut] = Field(default_factory=list)
    questions: list[QuestionPublic]


class AnswerIn(BaseModel):
    question_id: uuid.UUID
    chosen_index: int | None = Field(default=None, ge=0, le=3)
    essay_text: str | None = Field(default=None, max_length=8000)


class AnswerSavedOut(BaseModel):
    question_id: uuid.UUID
    answered_count: int
    total_count: int


class ReceiptRow(BaseModel):
    ordinal: int
    label: str
    qtype: str
    difficulty: str
    multiplier: float
    reward_seconds: float
    voided: bool = False
    void_reason: str | None = None
    score: float | None = None
    explanation: str | None = None



class ReceiptOut(BaseModel):
    session_id: uuid.UUID
    title: str | None
    base_reward_seconds: int
    rows: list[ReceiptRow]
    subtotal_seconds: float
    level_factor: float
    level_note: str
    novelty_factor: float
    novelty_note: str
    gross_seconds: float
    credited_seconds: int
    balance_seconds: int
    correct_count: int
    question_count: int
    streak_current: int
    new_badges: list[str]


class BadgeOut(BaseModel):
    code: str
    name: str
    hint: str
    earned: bool
    earned_at: datetime | None = None


class ProgressOut(BaseModel):
    subject_id: uuid.UUID
    streak_current: int
    streak_longest: int
    freeze_tokens: int
    sessions: int
    correct_total: int
    essay_passed: int
    badges: list[BadgeOut]


class DayPointOut(BaseModel):
    day: date
    earned_seconds: int
    consumed_seconds: int


class ReportOut(BaseModel):
    subject: SubjectOut
    standing: StandingOut
    days: list[DayPointOut]
    materials_studied: int
    correct_total: int
    essay_passed: int
    recent: list[LedgerEntryOut]
    guardian_alerts: list[str]
    device: BoundDeviceOut | None = None


class PushTokenIn(BaseModel):
    token: str = Field(min_length=16, max_length=4096)
    platform: Literal["android", "ios", "web"] = "android"


class HeartbeatIn(BaseModel):
    guardian_status: Literal["ok", "degraded", "disabled", "unknown"]
    events: list[dict] = Field(default_factory=list)


class AppRef(BaseModel):
    package: str
    label: str


class InstalledAppIn(BaseModel):
    package: str = Field(min_length=1, max_length=255)
    label: str = Field(min_length=1, max_length=120)
    is_system: bool = False
    version_name: str | None = Field(default=None, max_length=60)


class AppInventoryIn(BaseModel):
    apps: list[InstalledAppIn] = Field(min_length=1, max_length=1000)


class AppSyncOut(BaseModel):
    first_sync: bool
    changed: bool
    present: int
    installed: list[AppRef]
    uninstalled: list[AppRef]
    synced_at: datetime


class InstalledAppOut(BaseModel):
    package: str
    label: str
    is_system: bool
    version_name: str | None = None
    locked: bool
    is_new: bool
    first_seen_at: datetime
    last_seen_at: datetime
    removed_at: datetime | None = None


class AppChangeOut(BaseModel):
    occurred_at: datetime
    installed: list[AppRef]
    uninstalled: list[AppRef]


class AppInventoryOut(BaseModel):
    subject_id: uuid.UUID
    synced_at: datetime | None = None
    total: int
    locked_count: int
    apps: list[InstalledAppOut]
    recent_changes: list[AppChangeOut]


class OfflineQuestionOut(BaseModel):
    id: uuid.UUID
    qtype: str
    stem: str
    options: list[str]
    difficulty: str
    source_excerpt: str
    answer_hmac: str
