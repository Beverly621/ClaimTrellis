# ClaimTrellis v0.1 decisions and release gates

**Current status: ClaimTrellis v0.1 — P0 Accepted / P1.1–P1.3 Authorized / Pre-Release**

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
must remain open for human acceptance; no merge is authorized. P0's judgment core, six
labels, CLI and provider architecture remain unchanged. No dependency upgrades are needed.

P1.4 audit orchestration/quota redesign, P1.5 Matrix, P1.6 retrieval experiments and P1.7
full-workflow acceptance are not in scope. These first three stages neither call Jev nor
start audits. Workflow manuscript text (and, in P1.3, source text) is retained separately
from the existing minimal audit snapshot; operators must review [privacy](PRIVACY.md).
No release, visibility change, production migration/deployment or promotion is authorized.
See [the explicit stage contract](P1_PAPER_WORKFLOW.md).

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
