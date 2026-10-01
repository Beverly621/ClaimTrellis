# Account Access v1 — operator setup

Account Access is staged behind `CLAIM_TRELLIS_ACCOUNT_ACCESS_ENABLED` (default
`false`). Guest workspaces remain available. Supabase Auth owns credentials and
identity; ClaimTrellis stores only server-verified account metadata. No histories are
automatically merged when an email or Google identity belongs to another user.

## Deployment order

1. Deploy the Account v1 code while the flag remains `false`.
2. Apply `0003_user_profiles.sql` with `claim-trellis db migrate`, then confirm
   `claim-trellis db status` reports all migrations applied. The table has RLS and no
   Data API permissions for `anon` or `authenticated`.
3. In Supabase Auth, keep Anonymous Sign-Ins enabled; enable Email and Manual Identity
   Linking. In the Magic Link email template render `{{ .Token }}` to send a six-digit
   OTP. In Change Email Address, render the OTP for the new address. Verify the exact
   `email_change` flow with a disposable anonymous account and confirm its user ID
   remains unchanged.
4. Configure the verified `auth.trellis.ink` sending domain and transactional sender
   through Supabase's Resend integration or Custom SMTP. Keep its credential in
   Supabase only; do not place it in Vercel browser config or Git. Set a sensible
   OTP request cooldown and expiry, and keep marketing/tracking out of auth mail.
5. Configure a Google Cloud Web OAuth client in the Supabase Google provider. Copy
   Supabase's displayed callback URL exactly; allow only the production site redirect
   URL. Enable only basic identity/email scopes, not Gmail or Drive.
6. Test direct Email OTP, direct Google, guest-to-email, guest-to-Google, conflict,
   account sync and sign-out on a non-production identity. Only then set
   `CLAIM_TRELLIS_ACCOUNT_ACCESS_ENABLED=true` for the intended Vercel environments
   and redeploy.

Never paste database passwords, SMTP keys, OAuth secrets, or user OTPs into issues,
commits, screenshots, or logs.

## Account session regression acceptance — 2026-10-01

The session fix rechecks the current Supabase user before sign-out, listens for
session changes, and clears stale account/history views. Repeated sign-out is
idempotent. Linking retains the guest ID, including when the workspace is reopened
before verification; an unexpected identity blocks further protected requests.
Google callback conflicts are recoverable without silently switching accounts.
Transport/configuration failures are not presented as identity conflicts.

Automated validation: 59 Python tests against local PostgreSQL, 41 Node tests,
Ruff and strict mypy passed. An isolated Chrome smoke test with simulated Supabase
responses passed direct OTP/sign-out, guest email linking/cross-tab sign-out, and
Email/Google conflict plus explicit account switching. These are not real-provider
acceptance results.

Real Email OTP delivery/login was confirmed by the operator before this fix.
The operator also confirmed that the change-email OTP reached Gmail's inbox;
Outlook previously placed an auth email in junk. This does not verify Google OAuth
or guest ownership preservation. Email logo work is deferred.

Run the following with disposable test identities after loading the fixed assets:

| Flow | Required observation | Real-provider status |
| --- | --- | --- |
| Email login → sign-out | Profile disappears; Hero returns; refresh remains signed out; no new guest | Operator confirmed passed, 2026-10-01 |
| Direct Google | A signed-out user returns to the same test origin as a permanent account | Pending |
| Guest → Email | Record guest user ID and one audit ID, verify OTP, confirm exact same user ID and readable audit after refresh | Pending |
| Guest → Google | Record guest user ID and one audit ID, authorize linking, confirm exact same user ID and readable audit | Pending |
| Existing identity conflict | Original guest and audit remain; Keep guest preserves them; only explicit Switch accounts changes identity; histories stay separate | Pending |
| Cross-tab sign-out | Account details and history disappear in the other tab; refresh does not recreate a guest | Pending |

The operator enters OTPs and completes Google consent. Record only pass/fail and
whether IDs match, not credentials or identity details. For Google Testing mode,
use a configured test user. Local testing at `http://127.0.0.1:8768` requires that
exact origin in Supabase Auth's allowed redirect URLs; otherwise Supabase may send
the browser to the production Site URL. Do not change the Google client's Supabase
callback URI to localhost. Remove a temporary local redirect after acceptance.
Production Account Access remains gated until this matrix passes.
