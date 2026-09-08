CREATE TABLE installed_apps (
  subject_id    UUID NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
  package       TEXT NOT NULL,
  label         TEXT NOT NULL,
  is_system     BOOLEAN NOT NULL DEFAULT false,
  version_name  TEXT,
  device_id     UUID REFERENCES devices(id) ON DELETE SET NULL,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  removed_at    TIMESTAMPTZ,
  PRIMARY KEY (subject_id, package)
);

CREATE INDEX installed_apps_present_idx ON installed_apps(subject_id, label)
  WHERE removed_at IS NULL;

CREATE INDEX installed_apps_fresh_idx ON installed_apps(subject_id, first_seen_at DESC)
  WHERE removed_at IS NULL AND is_system = false;
