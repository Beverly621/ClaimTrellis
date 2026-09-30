-- ClaimTrellis hosted persistence. Applied by `claim-trellis db migrate`.
-- The runner provides the transaction and records the migration ID atomically.

CREATE TABLE IF NOT EXISTS claim_trellis_schema_migrations (
    migration_id TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audits (
    audit_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    record_json JSONB NOT NULL,
    CONSTRAINT uq_audits_id_owner UNIQUE (audit_id, owner_user_id)
);

CREATE INDEX IF NOT EXISTS idx_audits_owner_created
    ON audits (owner_user_id, created_at DESC, audit_id DESC);

CREATE TABLE IF NOT EXISTS audit_events (
    event_seq BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    audit_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    payload_json JSONB NOT NULL,
    CONSTRAINT fk_audit_events_owner
        FOREIGN KEY (audit_id, owner_user_id)
        REFERENCES audits (audit_id, owner_user_id)
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_audit_events_audit_seq
    ON audit_events (audit_id, event_seq);

CREATE INDEX IF NOT EXISTS idx_audit_events_owner_created
    ON audit_events (owner_user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS proposal_versions (
    proposal_id TEXT PRIMARY KEY,
    audit_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    snapshot_json JSONB NOT NULL,
    review_status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_proposal_audit_version UNIQUE (audit_id, version),
    CONSTRAINT fk_proposal_versions_owner
        FOREIGN KEY (audit_id, owner_user_id)
        REFERENCES audits (audit_id, owner_user_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_proposal_review_status CHECK (
        review_status IN (
            'pending_review', 'accepted', 'rejected', 'deferred',
            'revision_requested', 'revision_running', 'revision_failed', 'superseded'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_proposals_audit_version
    ON proposal_versions (audit_id, version);

CREATE TABLE IF NOT EXISTS revision_runs (
    revision_seq BIGSERIAL PRIMARY KEY,
    revision_id TEXT NOT NULL UNIQUE,
    audit_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    record_json JSONB NOT NULL,
    parent_status TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_revision_idempotency UNIQUE (audit_id, idempotency_key),
    CONSTRAINT fk_revision_runs_owner
        FOREIGN KEY (audit_id, owner_user_id)
        REFERENCES audits (audit_id, owner_user_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_revision_status CHECK (
        status IN (
            'revision_requested', 'revision_running', 'revision_failed', 'revision_completed'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_revisions_audit_seq
    ON revision_runs (audit_id, revision_seq);

CREATE UNIQUE INDEX IF NOT EXISTS uq_one_active_revision_per_audit
    ON revision_runs (audit_id)
    WHERE status IN ('revision_requested', 'revision_running');

-- Backend ownership checks are authoritative. Data API roles have no table access.
ALTER TABLE audits ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE proposal_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE revision_runs ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE audits FROM anon, authenticated;
REVOKE ALL ON TABLE audit_events FROM anon, authenticated;
REVOKE ALL ON TABLE proposal_versions FROM anon, authenticated;
REVOKE ALL ON TABLE revision_runs FROM anon, authenticated;
