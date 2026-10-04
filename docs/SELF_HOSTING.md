# Self-hosting

## Local development

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
claim-trellis serve
```

The default is a single-user SQLite workspace on `127.0.0.1:8000`. Without
`TYPESAFE_API_KEY`, parsing and deterministic checks work, but semantic decisions require
human review. SQLite/local auth is not a public multi-user security boundary.

## Hosted configuration

Set values through your deployment's secret/configuration store, not committed files:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Server-only PostgreSQL connection; TLS is required for hosted use |
| `CLAIM_TRELLIS_AUTH_MODE=supabase` | Verify Supabase identity and scope records by owner |
| `SUPABASE_URL` | Auth service URL |
| `SUPABASE_PUBLISHABLE_KEY` | Browser-safe publishable auth key, never a service-role key |
| `TYPESAFE_API_KEY` | Server-only optional Jev credential |
| `CLAIM_TRELLIS_HOSTED_PROVIDER_ENABLED` | Explicit opt-in to shared server-provider use |
| `CLAIM_TRELLIS_IP_HASH_SECRET` | Private random secret for quota IP HMACs |
| `CLAIM_TRELLIS_PAPER_DAILY_USER_LIMIT` | Rolling 24-hour paper-provider limit per user |
| `CLAIM_TRELLIS_PAPER_RUN_PROVIDER_LIMIT` | Provider-call limit per run |
| `CLAIM_TRELLIS_PAPER_MAX_CONCURRENT_PROVIDER_CALLS` | Global paper-provider concurrency limit |
| `CLAIM_TRELLIS_ACCOUNT_ACCESS_ENABLED` | Optional Email OTP/Google account access |
| `CLAIM_TRELLIS_API_DOCS_ENABLED` | Optional explicit API explorer override |

Hosted shared-provider use is disabled by default and fails closed if required secrets
or quotas are missing. Enabling it permits eligible users, including guests, to consume
the server's provider budget under existing user/IP/run/concurrency controls. Disabling
it blocks new shared-provider execution; it does not delete stored records.

Configure Supabase anonymous sign-ins for guest workspaces. For optional account access,
configure Email OTP, manual identity linking and Google basic identity/email scopes.
Use Supabase's exact Google callback URL and allow only intended site redirect URLs.
Login email templates must retain their OTP variable `{{ .Token }}`. Keep SMTP and OAuth
secrets in the corresponding service, never in browser code or public documentation.

## Database and deployment

Before deployment, obtain operator approval and a verified backup/restore plan. Inspect
and apply the included PostgreSQL migrations explicitly:

```sh
claim-trellis db status
claim-trellis db migrate
claim-trellis db status
```

Apply all migrations through `0005_paper_runs.sql` for the complete workflow.
Preview deployment does not authorize a production migration. Use a disposable database
to rehearse fresh migration, upgrade and backup restoration; never rehearse rollback on
user data. Tables use constraints/transactions and restricted Data API grants; server
owner scoping remains mandatory. Do not expose a service-role key in the frontend.

The existing Vercel entrypoint is `src.vercel_app:app`. Configure hosted environment
variables before deploying. The bundled web interface and `/api/v1/*` use the same app.
Use HTTPS and review auth/signup abuse controls before broad public use.

## API explorers

Local SQLite development enables `/docs`, `/redoc` and `/openapi.json` by default.
Supabase/PostgreSQL or shared-provider hosted mode disables them by default. The Vercel
entrypoint also defaults them off, even if a deployment accidentally uses local settings.
All three endpoints return 404 when disabled; the API routes and schemas stay unchanged.

Explicit `CLAIM_TRELLIS_API_DOCS_ENABLED=true` can enable them in a controlled non-production
environment; `false` disables them locally. This reduces production exposure, **not**
authentication: Supabase verification, owner scoping, constraints/transactions, quota
and input validation remain the security boundaries.

## Isolated engineering checks

Install `.[dev,e2e]` and Chromium with `python -m playwright install chromium`. Point
`TEST_DATABASE_URL` only at a disposable PostgreSQL database named `claim_trellis_test`.
Run `pytest`, `node --test web/*.test.js`, `ruff check .`, `ruff format --check .` and
`mypy`. Migration rehearsal requires `pg_dump`/`pg_restore`, or a disposable Docker test
container configured through `TEST_PG_CONTAINER`.

The acceptance fixtures are invented and licensed with the repository. Code/question
hashes are frozen in `tests/fixtures/contracts/workflow-freeze.json`. Browser tests use
explicit auth/provider doubles, not live user credentials. A separate opt-in live smoke
runner exists under `experiments/acceptance/`; it consumes real quota and retains ordinary
audit records, so do not include it in default tests. Integration success is not scientific
accuracy validation. Keep raw reports, uploads, credentials, backups and operational
notes outside the repository. See [privacy](PRIVACY.md) and [threat model](THREAT_MODEL.md).
