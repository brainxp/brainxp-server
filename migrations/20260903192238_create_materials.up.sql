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
