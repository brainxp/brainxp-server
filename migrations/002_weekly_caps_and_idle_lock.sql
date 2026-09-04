ALTER TABLE policies ADD COLUMN daily_caps JSONB;
ALTER TABLE policies ADD COLUMN daily_grants JSONB;
ALTER TABLE policies ADD COLUMN idle_days_allowed SMALLINT NOT NULL DEFAULT 2;
ALTER TABLE policies ADD CONSTRAINT policies_idle_ck
  CHECK (idle_days_allowed BETWEEN 0 AND 14);

UPDATE policies SET
  daily_caps = jsonb_build_array(
    daily_cap_seconds, daily_cap_seconds, daily_cap_seconds, daily_cap_seconds,
    daily_cap_seconds, daily_cap_seconds, daily_cap_seconds),
  daily_grants = '[0,0,0,0,0,0,0]'::jsonb;

ALTER TABLE policies ALTER COLUMN daily_caps SET NOT NULL;
ALTER TABLE policies ALTER COLUMN daily_caps SET DEFAULT '[3600,3600,3600,3600,3600,3600,3600]'::jsonb;
ALTER TABLE policies ALTER COLUMN daily_grants SET NOT NULL;
ALTER TABLE policies ALTER COLUMN daily_grants SET DEFAULT '[0,0,0,0,0,0,0]'::jsonb;

ALTER TABLE policies DROP COLUMN daily_cap_seconds;
ALTER TABLE policies DROP COLUMN balance_ceiling_seconds;
ALTER TABLE policies DROP COLUMN initial_grant_seconds;

ALTER TABLE daily_usage ADD COLUMN granted_at TIMESTAMPTZ;

ALTER TABLE quiz_sessions DROP COLUMN overflow_points;
ALTER TABLE progress DROP COLUMN points;
