CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";

CREATE TABLE users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email         TEXT UNIQUE,
  password_hash TEXT,
  auth_provider TEXT NOT NULL DEFAULT 'password',
  role          TEXT NOT NULL CHECK (role IN ('parent','child','personal')),
  display_name  TEXT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at    TIMESTAMPTZ,
  CONSTRAINT users_credential_ck CHECK (
    (role = 'child' AND email IS NULL AND password_hash IS NULL)
    OR (role <> 'child' AND email IS NOT NULL)
  )
);

CREATE TABLE families (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE family_members (
  family_id UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  user_id   UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role      TEXT NOT NULL CHECK (role IN ('parent','child','personal')),
  joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (family_id, user_id)
);

CREATE TABLE subjects (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id      UUID REFERENCES families(id) ON DELETE CASCADE,
  user_id        UUID REFERENCES users(id) ON DELETE SET NULL,
  display_name   TEXT NOT NULL,
  academic_level TEXT NOT NULL DEFAULT 'smp',
  kind           TEXT NOT NULL DEFAULT 'child',
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at     TIMESTAMPTZ,
  CONSTRAINT subjects_owner_ck CHECK (family_id IS NOT NULL OR user_id IS NOT NULL)
);
CREATE INDEX subjects_family_idx ON subjects(family_id) WHERE deleted_at IS NULL;

CREATE TABLE devices (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subject_id           UUID REFERENCES subjects(id) ON DELETE CASCADE,
  user_id              UUID REFERENCES users(id) ON DELETE CASCADE,
  device_secret_hash   TEXT NOT NULL,
  install_binding_hash TEXT,
  platform             TEXT NOT NULL DEFAULT 'android',
  model_name           TEXT,
  guardian_status      TEXT NOT NULL DEFAULT 'unknown',
  last_heartbeat_at    TIMESTAMPTZ,
  unbound_at           TIMESTAMPTZ,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX devices_binding_idx ON devices(install_binding_hash)
  WHERE install_binding_hash IS NOT NULL AND unbound_at IS NULL;
CREATE INDEX devices_subject_idx ON devices(subject_id);

CREATE TABLE refresh_tokens (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID REFERENCES users(id) ON DELETE CASCADE,
  device_id     UUID REFERENCES devices(id) ON DELETE CASCADE,
  token_hash    TEXT NOT NULL UNIQUE,
  family_chain  UUID NOT NULL,
  used_at       TIMESTAMPTZ,
  revoked_at    TIMESTAMPTZ,
  expires_at    TIMESTAMPTZ NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX refresh_chain_idx ON refresh_tokens(family_chain);

CREATE TABLE pairing_codes (
  code             TEXT PRIMARY KEY,
  family_id        UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  subject_id       UUID NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
  issued_by        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at       TIMESTAMPTZ NOT NULL,
  consumed_at      TIMESTAMPTZ,
  attempt_count    INT NOT NULL DEFAULT 0,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE policies (
  subject_id              UUID PRIMARY KEY REFERENCES subjects(id) ON DELETE CASCADE,
  questions_per_session   INT  NOT NULL DEFAULT 10  CHECK (questions_per_session BETWEEN 1 AND 50),
  base_reward_seconds     INT  NOT NULL DEFAULT 120 CHECK (base_reward_seconds BETWEEN 15 AND 1800),
  essay_ratio             NUMERIC(3,2) NOT NULL DEFAULT 0.20 CHECK (essay_ratio BETWEEN 0 AND 1),
  academic_level          TEXT NOT NULL DEFAULT 'smp',
  question_language       TEXT NOT NULL DEFAULT 'id',
  initial_grant_seconds   INT  NOT NULL DEFAULT 1800 CHECK (initial_grant_seconds >= 0),
  daily_cap_seconds       INT  NOT NULL DEFAULT 3600 CHECK (daily_cap_seconds > 0),
  balance_ceiling_seconds INT  NOT NULL DEFAULT 10800 CHECK (balance_ceiling_seconds > 0),
  day_reset_hour          INT  NOT NULL DEFAULT 5 CHECK (day_reset_hour BETWEEN 0 AND 23),
  allowed_upload_methods  TEXT[] NOT NULL DEFAULT ARRAY['photo','document'],
  locked_apps             JSONB  NOT NULL DEFAULT '[]'::jsonb,
  pending_weaken_at       TIMESTAMPTZ,
  pending_weaken_payload  JSONB,
  updated_by              UUID REFERENCES users(id) ON DELETE SET NULL,
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE materials (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subject_id      UUID NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
  source_type     TEXT NOT NULL,
  original_name   TEXT,
  content_sha256  TEXT NOT NULL,
  byte_size       BIGINT NOT NULL,
  page_count      INT,
  storage_key     TEXT,
  retention_mode  TEXT NOT NULL DEFAULT 'keep',
  status          TEXT NOT NULL DEFAULT 'uploaded'
                  CHECK (status IN ('uploaded','validating','rejected','generating','ready','failed')),
  declared_level  TEXT,
  assessed_level  TEXT,
  concept_density NUMERIC(4,3),
  detected_language TEXT,
  novelty_score   NUMERIC(4,3),
  gate_verdict    TEXT,
  gate_reason     TEXT,
  topic_summary   TEXT,
  embedding       VECTOR(1024),
  purged_at       TIMESTAMPTZ,
  last_studied_at TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at      TIMESTAMPTZ
);
CREATE INDEX materials_subject_idx ON materials(subject_id) WHERE deleted_at IS NULL;
CREATE INDEX materials_hash_idx ON materials(subject_id, content_sha256);

CREATE TABLE question_sets (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  material_id    UUID NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
  model_id       TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  requested_count INT NOT NULL,
  ready_count    INT NOT NULL DEFAULT 0,
  status         TEXT NOT NULL DEFAULT 'partial', -- partial | complete | degraded
  generated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE questions (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  question_set_id  UUID NOT NULL REFERENCES question_sets(id) ON DELETE CASCADE,
  batch_index      SMALLINT NOT NULL DEFAULT 0,
  ordinal          SMALLINT NOT NULL,
  qtype            TEXT NOT NULL CHECK (qtype IN ('mcq','essay')),
  stem             TEXT NOT NULL,
  options          JSONB,
  correct_index    SMALLINT,
  rubric           JSONB,
  reference_answer TEXT,
  source_excerpt   TEXT NOT NULL,
  explanation      TEXT,
  difficulty       TEXT NOT NULL CHECK (difficulty IN ('mudah','sedang','sulit')),
  bloom_level      TEXT NOT NULL,
  offline_hmac     TEXT,
  CONSTRAINT questions_shape_ck CHECK (
    (qtype='mcq'   AND options IS NOT NULL AND correct_index IS NOT NULL)
    OR (qtype='essay' AND rubric IS NOT NULL AND reference_answer IS NOT NULL)
  )
);
CREATE INDEX questions_set_idx ON questions(question_set_id, ordinal);

CREATE TABLE quiz_sessions (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subject_id        UUID NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
  question_set_id   UUID NOT NULL REFERENCES question_sets(id) ON DELETE CASCADE,
  question_order    JSONB NOT NULL,
  option_permutation JSONB NOT NULL,
  level_factor      NUMERIC(3,2) NOT NULL,
  novelty_factor    NUMERIC(3,2) NOT NULL,
  base_reward_seconds INT NOT NULL,
  correct_count     INT,
  reward_seconds    INT,
  overflow_points   INT,
  is_replay         BOOLEAN NOT NULL DEFAULT false,
  status            TEXT NOT NULL DEFAULT 'open',
  started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  submitted_at      TIMESTAMPTZ
);
CREATE INDEX quiz_subject_idx ON quiz_sessions(subject_id, started_at DESC);

CREATE TABLE quiz_answers (
  session_id      UUID NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,
  question_id     UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  chosen_index    SMALLINT,
  essay_text      TEXT,
  score           NUMERIC(5,2),
  is_correct      BOOLEAN,
  reward_seconds  NUMERIC(10,2),
  evaluator_notes TEXT,
  injection_flag  BOOLEAN NOT NULL DEFAULT false,
  answered_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (session_id, question_id)
);

CREATE TABLE time_ledger (
  id              BIGSERIAL PRIMARY KEY,
  subject_id      UUID NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
  delta_seconds   INT  NOT NULL,
  entry_type      TEXT NOT NULL CHECK (entry_type IN
                    ('initial','earned','consumed','granted','redeemed','penalty','adjustment','overflow')),
  note            TEXT,
  ref_id          UUID,
  client_event_id TEXT,
  device_id       UUID REFERENCES devices(id) ON DELETE SET NULL,
  occurred_at     TIMESTAMPTZ NOT NULL,
  recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ledger_idempotency_idx ON time_ledger(subject_id, client_event_id)
  WHERE client_event_id IS NOT NULL;
CREATE INDEX ledger_subject_idx ON time_ledger(subject_id, occurred_at DESC);

CREATE TABLE daily_usage (
  subject_id    UUID NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
  day_key       DATE NOT NULL,
  spent_seconds INT  NOT NULL DEFAULT 0,
  PRIMARY KEY (subject_id, day_key)
);

CREATE TABLE progress (
  subject_id     UUID PRIMARY KEY REFERENCES subjects(id) ON DELETE CASCADE,
  points         INT NOT NULL DEFAULT 0,
  streak_current INT NOT NULL DEFAULT 0,
  streak_longest INT NOT NULL DEFAULT 0,
  freeze_tokens  SMALLINT NOT NULL DEFAULT 0 CHECK (freeze_tokens BETWEEN 0 AND 2),
  last_study_day DATE,
  sessions       INT NOT NULL DEFAULT 0,
  correct_total  INT NOT NULL DEFAULT 0,
  hard_total     INT NOT NULL DEFAULT 0,
  essay_passed   INT NOT NULL DEFAULT 0,
  photo_total    INT NOT NULL DEFAULT 0,
  cross_lang     INT NOT NULL DEFAULT 0,
  perfect_total  INT NOT NULL DEFAULT 0
);

CREATE TABLE achievements (
  subject_id UUID NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
  badge_code TEXT NOT NULL,
  earned_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (subject_id, badge_code)
);

CREATE TABLE guardian_events (
  id          BIGSERIAL PRIMARY KEY,
  device_id   UUID REFERENCES devices(id) ON DELETE CASCADE,
  subject_id  UUID REFERENCES subjects(id) ON DELETE CASCADE,
  event_type  TEXT NOT NULL,
  payload     JSONB,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX guardian_subject_idx ON guardian_events(subject_id, occurred_at DESC);

CREATE TABLE audit_log (
  id            BIGSERIAL PRIMARY KEY,
  actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  action        TEXT NOT NULL,
  target        TEXT,
  payload       JSONB,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
