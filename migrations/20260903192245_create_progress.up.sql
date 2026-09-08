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
