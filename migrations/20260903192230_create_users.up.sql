CREATE TABLE users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email         TEXT UNIQUE,
  password_hash TEXT,
  auth_provider TEXT NOT NULL DEFAULT 'password',
  role          TEXT NOT NULL CHECK (role IN ('parent','child','personal')),
  display_name  TEXT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at    TIMESTAMPTZ,
  CONSTRAINT users_credential_ck CHECK (
    (role = 'child' AND email IS NULL AND password_hash IS NULL)
    OR (role <> 'child' AND email IS NOT NULL)
  )
);
