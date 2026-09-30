-- Server-owned account metadata. Supabase Auth remains the identity source.
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id TEXT PRIMARY KEY,
    user_email TEXT,
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    primary_auth_method TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ,
    product_updates_opt_in BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT ck_user_profiles_method CHECK (
        primary_auth_method IS NULL OR primary_auth_method IN ('email', 'google')
    )
);

CREATE INDEX IF NOT EXISTS idx_user_profiles_email
    ON user_profiles (lower(user_email)) WHERE user_email IS NOT NULL;

ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE user_profiles FROM anon, authenticated;
