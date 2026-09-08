CREATE TABLE achievements (
  subject_id UUID NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
  badge_code TEXT NOT NULL,
  earned_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (subject_id, badge_code)
);
