ALTER TABLE policies ADD COLUMN daily_cap_seconds INT NOT NULL DEFAULT 3600 CHECK (daily_cap_seconds > 0);
ALTER TABLE policies ADD COLUMN balance_ceiling_seconds INT NOT NULL DEFAULT 10800 CHECK (balance_ceiling_seconds > 0);
ALTER TABLE policies ADD COLUMN initial_grant_seconds INT NOT NULL DEFAULT 1800 CHECK (initial_grant_seconds >= 0);

UPDATE policies SET daily_cap_seconds = (daily_caps->>0)::int;

ALTER TABLE policies DROP COLUMN idle_days_allowed;
ALTER TABLE policies DROP COLUMN daily_grants;
ALTER TABLE policies DROP COLUMN daily_caps;
