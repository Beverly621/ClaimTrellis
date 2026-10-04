# ClaimTrellis v0.1 decisions and release gates

**Current status: ClaimTrellis v0.1 — P1 Paper Workflow Accepted 2026-10-03 / Feature Frozen / Pre-Release**

The v0.1 product direction is frozen. ClaimTrellis is an independent project and its only
primary brand. TypeSafe Jev is the first structured judgment provider and part of the
technical lineage, not the product identity.

## Feature-freeze policy

The product features, external API, data model, CLI commands, provider architecture, and
six-label judgment system are frozen except for the explicitly authorized work below. The owner has
confirmed the repository is now public. Do not publish
to PyPI, create a formal release, or perform promotional activity. New features and
nonessential dependency upgrades are paused.

Changes during the freeze are limited to:

- bug and security fixes;
- test, CI, type-checking, and reliability improvements;
- refactoring that does not change external behavior;
- documentation and benchmark preparation;
- UI refactoring explicitly requested by the repository owner; and
- domain or Vercel deployment configuration explicitly requested by the repository owner.

Do not run or claim the `<1% false-support rate` target without a formally adjudicated,
held-out benchmark. Do not change the brand, positioning, license, or release strategy
without an explicit decision from the repository owner.

## Repository development route

The owner confirmed public visibility and working Cloudflare/DNS/Vercel infrastructure.
This UI/review change does not alter that infrastructure or authorize a production deployment.
The default branch follows the standard safety policy for a mature repository:

- never force-push or delete `main`;
- develop every change on a separate branch and merge it through a pull request;
- require the `test` CI check to pass before merging;
- do not merge nonessential Dependabot upgrades during the feature freeze; and
- do not make the repository public merely to obtain branch-protection features.

Keep `main` protected with pull requests, the `test` status check, resolved conversations,
linear history, and blocked force-pushes and deletions. A
second-person approval is not required while the project has a single maintainer.

## Authorized P0: Core Audit Fidelity v2

The owner authorized P0 on 2026-10-03. This supersedes the general feature freeze only
for the existing claim-to-source audit pipeline: structured document blocks, deterministic
Top-K retrieval and context expansion, one to three selected evidence passages,
rule-based checks, Jev scientific alignment questions v3, fail-closed policy v2,
human evidence correction, versioned provenance/events, and the corresponding review UI
and regression benchmark. Preserve raw normalized text, legacy API fields, immutable
proposal history, ownership checks, quotas, and concurrency/idempotency guarantees.

The seven P0 decisions are fixed: one atomic claim and one identified source per audit;
multi-passage evidence sets; human-controlled evidence selection; separate scientific
alignment questions; no embeddings; no generated explanations; and no automatic final
acceptance. Explanations are assembled by policy code.

P0 was accepted by the owner on 2026-10-03 and PR #20 is merged. Hybrid retrieval,
P2 domain profiles, statistical validation, and cross-claim reasoning remain future
work. Do not add formats, OCR, scraping, chat, writing tools, paper scores, new providers,
billing, collaboration, account features, or a broad UI redesign. Repository visibility,
deployment configuration, brand, license, and release strategy are unchanged. No PyPI,
formal Release, deployment, promotion, or unvalidated accuracy claim is authorized.
See [the core capability roadmap](ROADMAP.md).

The owner confirmed on 2026-10-03 that all P0 implementation, tests, documentation and
follow-up fixes must stay in PR #20 (`codex/core-capability-roadmap`); do not open a second
P0 PR. This historical P0 scope ended with acceptance. The implementation contract is
[Core Audit Fidelity v2](P0_CORE_AUDIT_FIDELITY.md).

## Authorized P1.1–P1.3: backend Paper Workflow prototype

The owner authorized three separate PRs starting with #21 on 2026-10-03:
contracts/persistence, exact-span candidate extraction/human decisions, and bibliography/
uploaded-source mapping/human identity confirmation. PRs are stacked in that order and
were accepted on 2026-10-03 and merged in order after restacking. P0's judgment core, six
labels, CLI and provider architecture remain unchanged. No dependency upgrades are needed.

These first three stages neither call Jev nor
start audits. Workflow manuscript text (and, in P1.3, source text) is retained separately
from the existing minimal audit snapshot; operators must review [privacy](PRIVACY.md).
No release, visibility change, production migration/deployment or promotion is authorized.
See [the explicit stage contract](P1_PAPER_WORKFLOW.md).

## Authorized P1.4–P1.5: product workflow closure

The owner authorized one PR for run/item persistence, ordinary ClaimAudit execution,
idempotency/retry/paper-aware budgeting, Matrix projection and the browser Review Queue
on 2026-10-03. Implement P1.4a/b then P1.5a/b. The initial no-merge gate was later
superseded by the explicit merge/deployment authorization below, not by test results.
ClaimAudit remains the sole judgment unit; no PaperVerdict, paper score, bulk verdict,
new provider/dependency/CLI, retrieval/model/policy fork or account expansion.

P1.6 retrieval research and P1.7 full E2E/live Jev/migration rehearsal remain deferred.
Use synthetic data and mock providers for this PR. No production migration, release,
promotion or deployment configuration change is authorized. Paper provider quota numbers
need owner/operator decisions after cost testing; new budgets default to unconfigured
and fail closed, not an implicit increase to the existing hosted limits.

Implementation is ready for P1.4/P1.5 human acceptance; it is **not accepted**
by these automated checks. The stage contract lists the tests and local no-key synthetic
browser smoke. Owner decisions still required: functional acceptance, measured paper
budget values, confidential-data retention/deletion policy, and any separate production
backup/migration approval. P1.6/P1.7 remain unstarted.

### Authorized review and Vercel acceptance deployment — 2026-10-03

The owner subsequently authorized review fixes and deployment of the latest P1.4/P1.5
code to the existing Vercel website, keeping all changes in PR #24. The owner then
explicitly authorized merging PR #24 after green checks and deploying the `main` commit,
with real-paper/live-Jev acceptance consolidated at P1.5. This supersedes the earlier
no-merge/no-deployment/no-production-migration restrictions
only for this acceptance deployment. It is not a release or product acceptance.

The owner approved explicit paper quota values in Vercel and enabling the existing
Hosted Provider, including its existing Guest access and user/IP protections. The IP
HMAC secret stays solely in Vercel; API keys, database URLs, environment files and
backups must never enter Git. Deploy the reviewed `main` merge commit through the existing
Vercel production integration; do not promote an older preview or change branch tracking.

Before the approved additive `0004`/`0005` migrations, the seven existing application
tables were backed up to a Git-ignored local custom archive with mode `600`. Archive
inventory and SHA-256 were verified; this is an application-table backup, not a full
Supabase/Auth backup or a completed restore rehearsal. Both migrations were applied;
existing table row counts were unchanged; all seven new tables have RLS and no direct
`anon`/`authenticated` read/write grants. No original data was deleted.

Review fixes stop unscheduled queue calls after transport/render failures, drain requests
already in flight, correct preflight for running/unsafe/exhausted/cached items, and return
a sanitized 503 instead of an internal SQL failure when workflow tables are absent.

Real English-paper uploads, source-identity review and live Jev calls are exclusively
owner-operated. After that feedback, repair any defects before deciding on P1.6/P1.7;
neither stage is started or accepted by this deployment. The owner should request the
Hosted Provider be disabled and redeployed after testing; user/IP limits are not a
site-wide token budget. Functional acceptance and retention/deletion decisions remain
human gates. See [the manual handoff](P1_MANUAL_ACCEPTANCE.md).

## Authorized P1.6/P1.7 completion and small entry UI change — 2026-10-03

The owner reported that P1.5 manual acceptance and real Jev calls on real papers were
complete. They authorized P1.6/P1.7 in **one new PR**, green tests, merge and deployment
to the existing Vercel production website. The owner subsequently cancelled the proposed
Hosted Provider shutdown/removal: **keep it enabled**, with existing Guest/owner access
and unchanged quotas. Do not delete enable flags, API keys, IP secrets or database settings.

P1.6 is offline-only: optional experiment dependencies, fixed source-grounded corpus,
source/work-disjoint splits, lexical/dense/RRF comparison, metrics, provenance and report.
No production embedding adoption is authorized. Real-paper human-confirmed queries and
independently adjudicated qrels are not inferred from the existing seed/manual testing;
synthetic results remain engineering regression. Adoption needs a separate owner-approved
held-out benchmark and a separate retrieval-v3 adoption PR.

P1.7 freezes algorithms/contracts and verifies full workflow/traceability, real-browser
flows, two-case live integration and disposable PostgreSQL backup/restore. Live smoke
uses invented data and remains pending human review; it does not automate final judgment.
No new production migration, PyPI/formal Release, promotion, brand, license, provider,
CLI, relation-label or quota change is authorized.

The owner additionally requested a narrow homepage change in the same PR: equal hero
entry dimensions matching the left entry, no entry arrows, 📮 Sign in icon, and removal
of the shown hero eyebrow/overline/divider. Login and account behavior remain unchanged.

## Authorized v0.1 exception: UI and proposal revision loop

The owner authorized UI Design v1 and the minimum backend changes for versioned provider
proposals, human feedback, accept/reject/revise/defer, optimistic concurrency, idempotency,
failure recovery, and append-only lifecycle events. Six relation labels, CLI commands,
provider abstraction, brand, and license remain unchanged. No new dependencies are required.

This exception ends with the implementation on `codex/ui-design-v1`; further features
remain frozen. Review the PR before merging. No PyPI publication, formal Release,
production configuration change, or production deployment is authorized by this exception.
The owner's current public-repository update supersedes the older private-only wording
in the exception brief. See [the implementation contract](UI_AND_REVIEW_V1.md).

| Area | v0.1 decision |
|---|---|
| Display name | ClaimTrellis |
| Repository and distribution | `claim-trellis` |
| Python package | `claim_trellis` |
| CLI | `claim-trellis` |
| Environment prefix | `CLAIM_TRELLIS_` |
| Local data directory | `.claim-trellis/` |
| License | Apache-2.0 |
| Contribution governance | DCO; no CLA |
| Copyright | Contributors retain copyright |
| Primary users | Researchers and editorial reviewers |
| First domain | AI and machine-learning research |
| Second domain | Biomedical and life-science research |
| Semantic judgment | Provider interface; TypeSafe Jev is the default adapter |
| Relation labels | `supports`, `partially_supports`, `contradicts`, `not_addressed`, `insufficient_context`, `source_unavailable` |
| Automatic acceptance | Disabled for v0.1 |
| Final judgment | Always human-confirmed |
| Privacy | Local-first, no telemetry, minimum necessary provider payload |
| Evaluation safety target | False-support rate below 1% on an adjudicated held-out benchmark; not a product claim |
| Benchmark adjudication | Two independent annotators; third-party resolution of disagreements |
| Public history | New clean repository; private development repository retained as an archive |
| Blind test | Kept private |
| Public positioning | Verification/review infrastructure, never autonomous fact checking |

## Human release gates

The following require accountable human action before or during release:

1. Complete PyPI, GitHub, web, USPTO, WIPO, and target-market name checks. A free package
   name is not a trademark clearance.
2. Review actual source and dependency provenance. Copying code or assets can create
   license obligations even when public Git history starts clean.
3. Enable GitHub Private Vulnerability Reporting. Do not publish a personal email merely
   to fill a template field.
4. Appoint benchmark annotators and an adjudicator before making accuracy claims.
5. Review TypeSafe terms and institutional policy before sending confidential,
   unpublished, personal, or protected material.
6. Do not publish a performance claim until a frozen held-out evaluation is complete.

These gates do not block transparent experimental open-source publication. Releases must
remain `0.x experimental` until the validation and governance requirements are met.
