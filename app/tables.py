from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

meta = MetaData()
_uuid = UUID(as_uuid=True)


def _pk():
    return Column("id", _uuid, primary_key=True, server_default=func.gen_random_uuid())


users = Table(
    "users", meta, _pk(),
    Column("email", Text, unique=True),
    Column("password_hash", Text),
    Column("auth_provider", Text, nullable=False, server_default="password"),
    Column("role", Text, nullable=False),
    Column("display_name", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("deleted_at", DateTime(timezone=True)),
)

families = Table(
    "families", meta, _pk(),
    Column("owner_user_id", _uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

family_members = Table(
    "family_members", meta,
    Column("family_id", _uuid, ForeignKey("families.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", _uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role", Text, nullable=False),
    Column("joined_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

subjects = Table(
    "subjects", meta, _pk(),
    Column("family_id", _uuid, ForeignKey("families.id", ondelete="CASCADE")),
    Column("user_id", _uuid, ForeignKey("users.id", ondelete="SET NULL")),
    Column("display_name", Text, nullable=False),
    Column("academic_level", Text, nullable=False, server_default="smp"),
    Column("kind", Text, nullable=False, server_default="child"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("deleted_at", DateTime(timezone=True)),
)

devices = Table(
    "devices", meta, _pk(),
    Column("subject_id", _uuid, ForeignKey("subjects.id", ondelete="CASCADE")),
    Column("user_id", _uuid, ForeignKey("users.id", ondelete="CASCADE")),
    Column("device_secret_hash", Text, nullable=False),
    Column("install_binding_hash", Text),
    Column("platform", Text, nullable=False, server_default="android"),
    Column("model_name", Text),
    Column("guardian_status", Text, nullable=False, server_default="unknown"),
    Column("last_heartbeat_at", DateTime(timezone=True)),
    Column("unbound_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

refresh_tokens = Table(
    "refresh_tokens", meta, _pk(),
    Column("user_id", _uuid, ForeignKey("users.id", ondelete="CASCADE")),
    Column("device_id", _uuid, ForeignKey("devices.id", ondelete="CASCADE")),
    Column("token_hash", Text, nullable=False, unique=True),
    Column("family_chain", _uuid, nullable=False),
    Column("used_at", DateTime(timezone=True)),
    Column("revoked_at", DateTime(timezone=True)),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

pairing_codes = Table(
    "pairing_codes", meta,
    Column("code", Text, primary_key=True),
    Column("family_id", _uuid, ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
    Column("subject_id", _uuid, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False),
    Column("issued_by", _uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("consumed_at", DateTime(timezone=True)),
    Column("attempt_count", Integer, nullable=False, server_default="0"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

policies = Table(
    "policies", meta,
    Column("subject_id", _uuid, ForeignKey("subjects.id", ondelete="CASCADE"), primary_key=True),
    Column("questions_per_session", Integer, nullable=False, server_default="10"),
    Column("base_reward_seconds", Integer, nullable=False, server_default="120"),
    Column("essay_ratio", Numeric(3, 2), nullable=False, server_default="0.20"),
    Column("academic_level", Text, nullable=False, server_default="smp"),
    Column("question_language", Text, nullable=False, server_default="id"),
    Column("daily_caps", JSONB, nullable=False,
           server_default="[3600,3600,3600,3600,3600,3600,3600]"),
    Column("daily_grants", JSONB, nullable=False, server_default="[0,0,0,0,0,0,0]"),
    Column("idle_days_allowed", SmallInteger, nullable=False, server_default="2"),
    Column("day_reset_hour", Integer, nullable=False, server_default="5"),
    Column("allowed_upload_methods", ARRAY(Text), nullable=False),
    Column("locked_apps", JSONB, nullable=False, server_default="[]"),
    Column("pending_weaken_at", DateTime(timezone=True)),
    Column("pending_weaken_payload", JSONB),
    Column("updated_by", _uuid, ForeignKey("users.id", ondelete="SET NULL")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

materials = Table(
    "materials", meta, _pk(),
    Column("subject_id", _uuid, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False),
    Column("source_type", Text, nullable=False),
    Column("original_name", Text),
    Column("content_sha256", Text, nullable=False),
    Column("byte_size", BigInteger, nullable=False),
    Column("page_count", Integer),
    Column("storage_key", Text),
    Column("retention_mode", Text, nullable=False, server_default="keep"),
    Column("status", Text, nullable=False, server_default="uploaded"),
    Column("declared_level", Text),
    Column("assessed_level", Text),
    Column("concept_density", Numeric(4, 3)),
    Column("detected_language", Text),
    Column("novelty_score", Numeric(4, 3)),
    Column("gate_verdict", Text),
    Column("gate_reason", Text),
    Column("topic_summary", Text),
    Column("purged_at", DateTime(timezone=True)),
    Column("last_studied_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("deleted_at", DateTime(timezone=True)),
)

question_sets = Table(
    "question_sets", meta, _pk(),
    Column("material_id", _uuid, ForeignKey("materials.id", ondelete="CASCADE"), nullable=False),
    Column("model_id", Text, nullable=False),
    Column("prompt_version", Text, nullable=False),
    Column("requested_count", Integer, nullable=False),
    Column("ready_count", Integer, nullable=False, server_default="0"),
    Column("status", Text, nullable=False, server_default="partial"),
    Column("generated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

questions = Table(
    "questions", meta, _pk(),
    Column("question_set_id", _uuid, ForeignKey("question_sets.id", ondelete="CASCADE"), nullable=False),
    Column("batch_index", SmallInteger, nullable=False, server_default="0"),
    Column("ordinal", SmallInteger, nullable=False),
    Column("qtype", Text, nullable=False),
    Column("stem", Text, nullable=False),
    Column("options", JSONB),
    Column("correct_index", SmallInteger),
    Column("rubric", JSONB),
    Column("reference_answer", Text),
    Column("source_excerpt", Text, nullable=False),
    Column("explanation", Text),
    Column("difficulty", Text, nullable=False),
    Column("bloom_level", Text, nullable=False),
    Column("offline_hmac", Text),
)

quiz_sessions = Table(
    "quiz_sessions", meta, _pk(),
    Column("subject_id", _uuid, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False),
    Column("question_set_id", _uuid, ForeignKey("question_sets.id", ondelete="CASCADE"), nullable=False),
    Column("question_order", JSONB, nullable=False),
    Column("option_permutation", JSONB, nullable=False),
    Column("level_factor", Numeric(3, 2), nullable=False),
    Column("novelty_factor", Numeric(3, 2), nullable=False),
    Column("base_reward_seconds", Integer, nullable=False),
    Column("correct_count", Integer),
    Column("reward_seconds", Integer),
    Column("is_replay", Boolean, nullable=False, server_default="false"),
    Column("status", Text, nullable=False, server_default="open"),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("submitted_at", DateTime(timezone=True)),
)

quiz_answers = Table(
    "quiz_answers", meta,
    Column("session_id", _uuid, ForeignKey("quiz_sessions.id", ondelete="CASCADE"), primary_key=True),
    Column("question_id", _uuid, ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True),
    Column("chosen_index", SmallInteger),
    Column("essay_text", Text),
    Column("score", Numeric(5, 2)),
    Column("is_correct", Boolean),
    Column("reward_seconds", Numeric(10, 2)),
    Column("evaluator_notes", Text),
    Column("injection_flag", Boolean, nullable=False, server_default="false"),
    Column("answered_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

time_ledger = Table(
    "time_ledger", meta,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("subject_id", _uuid, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False),
    Column("delta_seconds", Integer, nullable=False),
    Column("entry_type", Text, nullable=False),
    Column("note", Text),
    Column("ref_id", _uuid),
    Column("client_event_id", Text),
    Column("device_id", _uuid, ForeignKey("devices.id", ondelete="SET NULL")),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

daily_usage = Table(
    "daily_usage", meta,
    Column("subject_id", _uuid, ForeignKey("subjects.id", ondelete="CASCADE"), primary_key=True),
    Column("day_key", Date, primary_key=True),
    Column("spent_seconds", Integer, nullable=False, server_default="0"),
    Column("granted_at", DateTime(timezone=True)),
)

progress = Table(
    "progress", meta,
    Column("subject_id", _uuid, ForeignKey("subjects.id", ondelete="CASCADE"), primary_key=True),
    Column("streak_current", Integer, nullable=False, server_default="0"),
    Column("streak_longest", Integer, nullable=False, server_default="0"),
    Column("freeze_tokens", SmallInteger, nullable=False, server_default="0"),
    Column("last_study_day", Date),
    Column("sessions", Integer, nullable=False, server_default="0"),
    Column("correct_total", Integer, nullable=False, server_default="0"),
    Column("hard_total", Integer, nullable=False, server_default="0"),
    Column("essay_passed", Integer, nullable=False, server_default="0"),
    Column("photo_total", Integer, nullable=False, server_default="0"),
    Column("cross_lang", Integer, nullable=False, server_default="0"),
    Column("perfect_total", Integer, nullable=False, server_default="0"),
)

achievements = Table(
    "achievements", meta,
    Column("subject_id", _uuid, ForeignKey("subjects.id", ondelete="CASCADE"), primary_key=True),
    Column("badge_code", Text, primary_key=True),
    Column("earned_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

guardian_events = Table(
    "guardian_events", meta,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("device_id", _uuid, ForeignKey("devices.id", ondelete="CASCADE")),
    Column("subject_id", _uuid, ForeignKey("subjects.id", ondelete="CASCADE")),
    Column("event_type", Text, nullable=False),
    Column("payload", JSONB),
    Column("occurred_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

audit_log = Table(
    "audit_log", meta,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("actor_user_id", _uuid, ForeignKey("users.id", ondelete="SET NULL")),
    Column("action", Text, nullable=False),
    Column("target", Text),
    Column("payload", JSONB),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
