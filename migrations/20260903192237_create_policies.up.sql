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
