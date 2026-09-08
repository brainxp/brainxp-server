CREATE TABLE time_ledger (
  id              BIGSERIAL PRIMARY KEY,
  subject_id      UUID NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
  delta_seconds   INT  NOT NULL,
  entry_type      TEXT NOT NULL CHECK (entry_type IN
                    ('initial','earned','consumed','granted','redeemed','penalty','adjustment','overflow')),
  note            TEXT,
  ref_id          UUID,
  client_event_id TEXT,
  device_id       UUID REFERENCES devices(id) ON DELETE SET NULL,
  occurred_at     TIMESTAMPTZ NOT NULL,
  recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ledger_idempotency_idx ON time_ledger(subject_id, client_event_id)
  WHERE client_event_id IS NOT NULL;
CREATE INDEX ledger_subject_idx ON time_ledger(subject_id, occurred_at DESC);
