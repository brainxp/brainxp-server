CREATE TABLE question_sets (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  material_id    UUID NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
  model_id       TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  requested_count INT NOT NULL,
  ready_count    INT NOT NULL DEFAULT 0,
  status         TEXT NOT NULL DEFAULT 'partial',
  generated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
