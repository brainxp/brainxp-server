CREATE TABLE devices (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subject_id           UUID REFERENCES subjects(id) ON DELETE CASCADE,
  user_id              UUID REFERENCES users(id) ON DELETE CASCADE,
  device_secret_hash   TEXT NOT NULL,
  install_binding_hash TEXT,
  platform             TEXT NOT NULL DEFAULT 'android',
  model_name           TEXT,
  guardian_status      TEXT NOT NULL DEFAULT 'unknown',
  last_heartbeat_at    TIMESTAMPTZ,
  unbound_at           TIMESTAMPTZ,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX devices_binding_idx ON devices(install_binding_hash)
  WHERE install_binding_hash IS NOT NULL AND unbound_at IS NULL;
CREATE INDEX devices_subject_idx ON devices(subject_id);
