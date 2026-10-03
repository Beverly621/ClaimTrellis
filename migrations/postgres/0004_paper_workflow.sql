-- P1.1 contracts only. Never creates or executes a ClaimAudit.
CREATE TABLE IF NOT EXISTS research_projects (
    project_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    creation_sha256 TEXT NOT NULL,
    record_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, owner_user_id)
);
CREATE TABLE IF NOT EXISTS paper_workflow_records (
    record_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    parent_id TEXT,
    creation_sha256 TEXT NOT NULL,
    record_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (record_id, project_id, owner_user_id),
    FOREIGN KEY (project_id, owner_user_id) REFERENCES research_projects (project_id, owner_user_id),
    FOREIGN KEY (parent_id, project_id, owner_user_id)
        REFERENCES paper_workflow_records (record_id, project_id, owner_user_id)
);
CREATE INDEX IF NOT EXISTS idx_workflow_project_kind ON paper_workflow_records
    (project_id, owner_user_id, kind, created_at, record_id);
CREATE TABLE IF NOT EXISTS paper_workflow_events (
    event_seq BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    project_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    record_id TEXT,
    event_type TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (project_id, owner_user_id) REFERENCES research_projects (project_id, owner_user_id)
);
CREATE INDEX IF NOT EXISTS idx_workflow_events ON paper_workflow_events
    (project_id, owner_user_id, event_seq);
ALTER TABLE research_projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE paper_workflow_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE paper_workflow_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE research_projects, paper_workflow_records, paper_workflow_events FROM anon, authenticated;
