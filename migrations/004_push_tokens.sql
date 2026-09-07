CREATE TABLE push_tokens (
  token        TEXT PRIMARY KEY,
  user_id      UUID REFERENCES users(id) ON DELETE CASCADE,
  device_id    UUID REFERENCES devices(id) ON DELETE CASCADE,
  platform     TEXT NOT NULL DEFAULT 'android'
                 CHECK (platform IN ('android','ios','web')),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  revoked_at   TIMESTAMPTZ,
  CHECK (user_id IS NOT NULL OR device_id IS NOT NULL)
);

CREATE INDEX push_tokens_user_idx ON push_tokens(user_id)
  WHERE revoked_at IS NULL AND user_id IS NOT NULL;

CREATE INDEX push_tokens_device_idx ON push_tokens(device_id)
  WHERE revoked_at IS NULL AND device_id IS NOT NULL;
