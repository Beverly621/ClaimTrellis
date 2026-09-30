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
