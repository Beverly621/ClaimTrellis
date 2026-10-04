-- Orchestration only. No paper-level verdict or score.
CREATE TABLE paper_audit_runs (
 run_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, owner_user_id TEXT NOT NULL,
 creation_sha256 TEXT NOT NULL, record_json JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL,
 UNIQUE(run_id,project_id,owner_user_id),
 FOREIGN KEY(project_id,owner_user_id) REFERENCES research_projects(project_id,owner_user_id)
);
CREATE TABLE paper_audit_items (
 item_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, project_id TEXT NOT NULL, owner_user_id TEXT NOT NULL,
 source_link_id TEXT NOT NULL, record_json JSONB NOT NULL, checkpoint_json JSONB,
 lease_token TEXT, lease_until TIMESTAMPTZ, requests_json JSONB NOT NULL,
 UNIQUE(item_id,project_id,owner_user_id), UNIQUE(project_id,owner_user_id,source_link_id),
 FOREIGN KEY(run_id,project_id,owner_user_id) REFERENCES paper_audit_runs(run_id,project_id,owner_user_id),
 FOREIGN KEY(source_link_id,project_id,owner_user_id) REFERENCES paper_workflow_records(record_id,project_id,owner_user_id)
);
CREATE TABLE paper_run_members (
 run_id TEXT NOT NULL, item_id TEXT NOT NULL, project_id TEXT NOT NULL, owner_user_id TEXT NOT NULL,
 PRIMARY KEY(run_id,item_id),
 FOREIGN KEY(run_id,project_id,owner_user_id) REFERENCES paper_audit_runs(run_id,project_id,owner_user_id),
 FOREIGN KEY(item_id,project_id,owner_user_id) REFERENCES paper_audit_items(item_id,project_id,owner_user_id)
);
CREATE TABLE paper_provider_usage (
 usage_id TEXT PRIMARY KEY, item_id TEXT NOT NULL, run_id TEXT NOT NULL, project_id TEXT NOT NULL,
 owner_user_id TEXT NOT NULL, lease_token TEXT NOT NULL, status TEXT NOT NULL,
 result_json JSONB, error_code TEXT, created_at TIMESTAMPTZ NOT NULL, completed_at TIMESTAMPTZ,
 CHECK(status IN ('started','succeeded','failed','unknown')),
 FOREIGN KEY(item_id,project_id,owner_user_id) REFERENCES paper_audit_items(item_id,project_id,owner_user_id),
 FOREIGN KEY(run_id,project_id,owner_user_id) REFERENCES paper_audit_runs(run_id,project_id,owner_user_id)
);
CREATE INDEX idx_paper_usage_owner ON paper_provider_usage(owner_user_id,created_at);
CREATE INDEX idx_paper_usage_item ON paper_provider_usage(item_id,created_at);
ALTER TABLE paper_audit_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE paper_audit_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE paper_run_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE paper_provider_usage ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE paper_audit_runs,paper_audit_items,paper_run_members,paper_provider_usage FROM anon,authenticated;
