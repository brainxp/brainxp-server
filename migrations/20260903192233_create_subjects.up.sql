CREATE TABLE subjects (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id      UUID REFERENCES families(id) ON DELETE CASCADE,
  user_id        UUID REFERENCES users(id) ON DELETE SET NULL,
  display_name   TEXT NOT NULL,
  academic_level TEXT NOT NULL DEFAULT 'smp',
  kind           TEXT NOT NULL DEFAULT 'child',
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at     TIMESTAMPTZ,
  CONSTRAINT subjects_owner_ck CHECK (family_id IS NOT NULL OR user_id IS NOT NULL)
);
CREATE INDEX subjects_family_idx ON subjects(family_id) WHERE deleted_at IS NULL;
