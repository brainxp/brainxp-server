CREATE TABLE guardian_alerts (
  id              BIGSERIAL PRIMARY KEY,
  subject_id      UUID NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
  device_id       UUID REFERENCES devices(id) ON DELETE SET NULL,
  kind            TEXT NOT NULL CHECK (kind IN
                    ('accessibility_off','usage_access_off','overlay_off',
                     'protection_disabled','device_silent')),
  detail          TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  acknowledged_at TIMESTAMPTZ,
  resolved_at     TIMESTAMPTZ
);

CREATE UNIQUE INDEX guardian_alerts_open_idx ON guardian_alerts(subject_id, kind)
  WHERE acknowledged_at IS NULL AND resolved_at IS NULL;

CREATE INDEX guardian_alerts_feed_idx ON guardian_alerts(subject_id, created_at DESC);
