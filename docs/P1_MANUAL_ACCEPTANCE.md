# P1.4 / P1.5: owner-operated real-paper acceptance

Status: reviewed software, awaiting human real-paper/Jev acceptance at P1.5. The owner
separately authorized PR #24 merge/deployment after green checks; merge is not acceptance.
This is not P1.6 retrieval research, P1.7 full E2E/rehearsal, scientific validation or
a held-out accuracy benchmark. No false-support-rate claim follows from these tests.

## Preparation

Use the existing production website's `/projects` page after signing in or explicitly
continuing as Guest. Use one stable account; a different browser/account has a different
owner workspace. Prefer a permanent account for artifacts you need to retain.

Select English research from the last four years in authoritative journals or leading
venues in the relevant field. Upload only legally usable material you are permitted to
send to TypeSafe; exclude confidential/unpublished/personal/clinical patient data. The
application does not verify venue prestige, publication dates, licenses or scientific truth.
Manuscript/source text persists; read [privacy](PRIVACY.md).

The operator has approved production migrations and explicit server-side quotas for
this acceptance window. Hosted calls use the server's key, including calls by Guests;
visitors never receive the key. These are call limits, not a global token/spending cap.

## Manual checks

1. Create a project and upload a manuscript with citation-bearing English claims.
   Extract exact-span candidates and parse its reference section. Inspect offsets,
   original text and extraction warnings. Unrecognized references require manual spans.
2. Confirm/Edit/Reject each candidate yourself, explicitly checking Atomicity,
   Faithfulness and Necessary Context. An edited claim is separate from its immutable
   original span. No audit or Jev call should happen here.
3. Upload the actual cited sources (PDF/DOCX/MD/TXT). Inspect parsed text and source
   hashes; scan/image-only PDFs are not OCR-supported. Enter accurate title/DOI/year
   metadata, then inspect mapping suggestions. Metadata matching is not proof of identity.
4. Confirm source identity only after checking the actual reference and uploaded paper.
   Keep one mapping unconfirmed/unmapped and one claim rejected to check the gates.
   One claim with two sources must remain two separately reviewable links.
5. Select confirmed links, leave **Use configured judgment provider** checked, and Plan.
   Planning must create no ordinary audit and make no model call. Inspect the estimated
   quota; it is not a reservation or guarantee of provider availability.
6. Execute once. This is the first intentional real Jev call. Inspect every completed
   ordinary audit: selected passages/locators, raw six-label relation, policy proposal,
   service errors and human state. `completed` is an operational status, not "supports".
   A service failure must not be silently presented as successful semantic evaluation.
7. Open an ordinary audit from its Matrix row. Compare evidence with the paper yourself,
   then Accept/Reject/Defer or request Revision using the existing console. Each row
   keeps its own source, audit, policy and human decision; no paper-level score/verdict.
8. Return to the same project's Matrix, refresh and verify stable row IDs, stored decisions,
   proposal versions and event history. Replaying a completed item must not create a
   second initial audit/model call. Semantic re-evaluation uses ordinary Revision.
9. Check stale human decisions in a second tab; logout/account switch must clear private
   content. Do not deliberately exhaust public quotas or interrupt paid calls merely to
   reproduce failures; those paths already have disposable-database/mock regressions.

## Feedback needed to continue

Report the project, row/run/item/audit IDs; source title/DOI and text hash; the failing
step; expected versus actual result; relevant evidence locator; and sanitized error or
screenshot. Include whether the problem is parsing/retrieval, source identity, model
judgment, policy, human review, persistence or UI. Never send API keys, bearer tokens,
database URLs, browser local-storage/session dumps or unredacted network headers.

When finished, explicitly request **disable Hosted Provider and redeploy**. That prevents
new hosted Jev evaluations; it does not cancel an already-started request, erase stored
audits or delete keys/data. Review, history and deterministic-only workflows remain.
After feedback-driven repairs and explicit human acceptance, the owner decides whether
to authorize P1.6/P1.7; this checklist does not auto-advance or auto-merge.
