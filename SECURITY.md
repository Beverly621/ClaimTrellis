# Security policy

## Reporting a vulnerability

Use GitHub Private Vulnerability Reporting for this repository. Do not open a public issue
containing an unpatched vulnerability, API key, manuscript, patient information, or
private source. A dedicated project address may be added after a project domain is
established; no personal email is published merely to fill this field.

## Secrets

- `TYPESAFE_API_KEY` is read only from the process environment.
- The API never returns the key or logs authorization headers.
- `.env*`, `*.key`, local databases, uploads, caches, and reports are ignored by Git.
- CI does not require or receive a production API key.
- `DATABASE_URL` is server-only. The browser receives only the Supabase project URL and
  publishable key; no secret/service-role key or database password is exposed.

## Supported versions

Security fixes are provided for the current minor release until a formal release policy
is adopted.

## Deployment baseline

Run behind TLS, set explicit upload and request-size limits at the reverse proxy, restrict
the data directory to the service account, and do not expose a development server directly
to the internet. The built-in server is intended for local use and controlled evaluation.
Hosted mode verifies Supabase Auth tokens server-side and scopes every persisted audit
operation to the verified user ID. PostgreSQL row locks and constraints, not in-process
locks, protect concurrent lifecycle mutations. RLS is enabled and direct `anon` and
`authenticated` table privileges are revoked as defense in depth. Local SQLite mode is
single-user and must not be treated as an internet-facing multi-user isolation boundary.
Before broad public use, enable CAPTCHA/Turnstile for anonymous signup and enforce a
per-user provider usage guard; the hosted paid-provider path is off by default.
