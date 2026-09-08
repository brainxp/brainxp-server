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
