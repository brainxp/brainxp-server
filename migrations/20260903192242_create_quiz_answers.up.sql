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
