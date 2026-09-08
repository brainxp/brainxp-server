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
