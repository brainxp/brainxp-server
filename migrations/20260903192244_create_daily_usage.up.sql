CREATE TABLE daily_usage (
  subject_id    UUID NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
  day_key       DATE NOT NULL,
  spent_seconds INT  NOT NULL DEFAULT 0,
  PRIMARY KEY (subject_id, day_key)
);
