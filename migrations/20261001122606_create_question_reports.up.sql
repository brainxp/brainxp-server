CREATE TABLE question_reports (
  id            BIGSERIAL PRIMARY KEY,
  session_id    UUID NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,
  question_id   UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  subject_id    UUID NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
  reporter_role TEXT NOT NULL,
  reason        TEXT NOT NULL CHECK (reason IN
                  ('kunci_salah','soal_tidak_jelas','di_luar_materi','lainnya')),
  note          TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  reviewed_at   TIMESTAMPTZ,
  UNIQUE (session_id, question_id)
);

CREATE INDEX question_reports_queue_idx ON question_reports(updated_at)
  WHERE reviewed_at IS NULL;
