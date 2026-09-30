-- Hosted provider quota reservations. The application owns access and Data API roles do not.
CREATE TABLE IF NOT EXISTS provider_usage (
    usage_seq BIGSERIAL PRIMARY KEY,
    usage_id TEXT NOT NULL UNIQUE,
    owner_user_id TEXT NOT NULL,
    ip_hash TEXT NOT NULL,
    audit_id TEXT,
    provider TEXT NOT NULL,
    operation TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    input_tokens INTEGER,
    output_tokens INTEGER,
    error_code TEXT,
    CONSTRAINT ck_provider_usage_operation CHECK (operation IN ('audit', 'revision')),
    CONSTRAINT ck_provider_usage_status CHECK (status IN ('started', 'succeeded', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_provider_usage_owner_created
    ON provider_usage (owner_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_provider_usage_ip_created
    ON provider_usage (ip_hash, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_provider_usage_audit_operation
    ON provider_usage (audit_id, operation, created_at DESC);

ALTER TABLE provider_usage ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE provider_usage FROM anon, authenticated;
