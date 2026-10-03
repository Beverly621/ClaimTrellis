# ClaimTrellis

**Auditable claim-to-source verification with human final judgment.**

ClaimTrellis is an independent open-source system for determining whether source evidence
supports written claims. It combines deterministic parsing and numeric checks, local
evidence retrieval, structured probabilistic judgments, and an explicit human decision
trail.

ClaimTrellis develops the citation-verification pattern demonstrated with TypeSafe Jev
into a general-purpose verification stack with deterministic retrieval, provider-neutral
structured judgment, provenance tracking, human adjudication, and reproducible audit
trails. Jev is the default provider, not the product identity.

The project is deliberately **not** marketed as an autonomous fact checker. It answers a
narrower and testable question: *does this identified source, in the supplied context,
support this claim?*

## Trust model

- Code owns file parsing, exact quote matching, numeric comparison, identifiers, dates,
  policy, and persistence.
- Retrieval narrows a source to short candidate passages before any model call.
- A provider interface supplies narrow semantic judgments; the default Jev adapter asks
  independent questions in parallel and never generates evidence.
- No model verdict becomes a final human verdict. Automatic acceptance remains disabled
  in P0; model confidence never authorizes an Accept action.
- Every result records its source locator, evidence text hash, question-set version,
  model version, probabilities, policy version, and reviewer action.

Read [the trust specification](docs/TRUST_SPEC.md) before deploying the software.

## Current capabilities

- Parse English `.txt`, `.md`, `.pdf`, and `.docx` files.
- Detect numeric and author-year citation markers and produce citation-bearing sentences.
- Preserve normalized text with structured blocks and grounded page, heading, paragraph
  or line locators where the source format provides them.
- Retrieve up to ten candidates by default using deterministic BM25-style lexical
  ranking, explicit feature boosts, bounded adjacent context and de-duplication.
- Judge an evidence set of one to three source passages; let reviewers correct that set
  through a new immutable proposal version.
- Run versioned quote, number, unit, range, lexical direction, comparator, citation and
  completeness checks in code. Identity and scientific interpretation still need review.
- Ask the configured provider for relation, claim type, population, intervention,
  comparator, outcome, timeframe, direction, scope, causal-fidelity, evidence-sufficiency
  and injection signals in one request.
- Distinguish `supports`, `partially_supports`, `contradicts`, `not_addressed`,
  `insufficient_context`, and `source_unavailable`.
- Apply a fail-closed decision policy and capture a final human review separately.
- Accept, reject, defer, or request a new provider proposal with human feedback; retain
  every proposal version and protect against stale or concurrent review actions.
- Persist audits locally in SQLite or in owner-scoped PostgreSQL for hosted workspaces,
  with append-only audit events.
- Run through a CLI, REST API, or the included accessible review interface.
- Evaluate predictions with accuracy, per-label precision/recall/F1, Brier score, expected
  calibration error, coverage, and selective risk.

## Quick start

An experimental, backend-only Paper Workflow contract is available under
`/api/v1/projects`. P1.1 adds owner-scoped project/manuscript records, P1.2 proposes
exact-span claims for human decisions, and P1.3 maps bibliography entries to uploaded
sources with human identity confirmation. It does not perform whole-paper audits.
Each P1 stage requires separate human acceptance; the browser workflow UI is deferred.
See [the stage boundaries](docs/P1_PAPER_WORKFLOW.md) and [retention](docs/PRIVACY.md).

Requirements: Python 3.11 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
claim-trellis serve
```

Open `http://127.0.0.1:8000`. Without a provider API key the system runs its deterministic
checks and routes every semantic decision to human review.

To enable Jev for the current shell only:

```bash
export TYPESAFE_API_KEY='your-key-from-console.typesafe.ai'
claim-trellis serve
```

Do not place the key in source files. Local `.env*`, private uploads, databases, caches,
and evaluation outputs are ignored by Git.

## CLI examples

```bash
# Audit a claim against a local source. The output is JSON.
claim-trellis audit \
  --claim "The intervention reduced the primary composite cardiovascular endpoint." \
  --source paper.pdf \
  --citation "doi:10.1056/NEJMoa2307563"

# Validate and summarize the curated seed benchmark without calling Jev.
claim-trellis benchmark validate benchmarks/literature_seed.jsonl

# Run the pinned default-provider question set. Responses are cached locally.
claim-trellis benchmark run benchmarks/literature_seed.jsonl

# Score a JSONL predictions file against gold labels.
claim-trellis benchmark score \
  benchmarks/literature_seed.jsonl reports/local/predictions.jsonl
```

## API outline

- `GET /healthz` — health and model configuration, never the API key.
- `GET /api/v1/auth/config` — browser-safe anonymous-auth configuration.
- `GET /api/v1/audits` — current workspace history, with limit/offset pagination.
- `POST /api/v1/documents/parse` — parse an uploaded English source.
- `POST /api/v1/evidence/search` — return ranked candidate passages.
- `POST /api/v1/audits` — run deterministic and optional Jev checks.
- `GET /api/v1/audits/{audit_id}` — retrieve the full audit record.
- `POST /api/v1/audits/{audit_id}/reviews` — record the human decision.
- `POST /api/v1/audits/{audit_id}/revisions` — re-evaluate with feedback and an idempotency key.
- `GET /api/v1/audits/{audit_id}/proposals/current` — inspect the current proposal.
- `GET /api/v1/audits/{audit_id}/proposals` — inspect all proposal versions and lifecycle states.
- `GET /api/v1/audits/{audit_id}/revisions` — inspect revision attempts, including failures.
- `GET /api/v1/audits/{audit_id}/events` — retrieve the append-only audit trail.

Interactive API documentation is available at `/docs` while the service is running.
See [UI and review-loop contracts](docs/UI_AND_REVIEW_V1.md) for concurrency, migration,
and compatibility details, and [P0 Core Audit Fidelity](docs/P0_CORE_AUDIT_FIDELITY.md)
for additive evidence-selection fields and versioned contracts.

## Hosted anonymous workspaces

Without `DATABASE_URL`, the default remains a local, single-user SQLite workspace; it is
not a public multi-user security boundary. Hosted mode requires PostgreSQL and Supabase
Auth together. Set `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, and
`CLAIM_TRELLIS_AUTH_MODE=supabase` in the server environment, then run
`claim-trellis db status` and `claim-trellis db migrate` explicitly before deploying.
The database URL is server-only. The browser creates or restores a Supabase anonymous
session, and the API verifies its token before returning owner-scoped records.

The console shows recent records; `/history` shows a paginated workspace history. An
audit URL such as `/?audit=<id>#result` reopens that owned record after refresh. No email
is requested. Clearing browser data, signing out, or changing devices before account
linking can make that anonymous workspace inaccessible, although its records remain on
the server. Account Access v1 adds optional Email OTP and Google linking behind
`CLAIM_TRELLIS_ACCOUNT_ACCESS_ENABLED`; see [operator setup](docs/ACCOUNT_SETUP.md)
before enabling it.

Hosted paid-provider calls are disabled by default. Migration `0002_provider_usage.sql`
adds database-atomic reservations: 7 evaluations per user and 10 per public IP in a
rolling 24 hours, plus 5 provider revisions per audit. Set a private, random
`CLAIM_TRELLIS_IP_HASH_SECRET` on the server; raw IPs are not stored. Apply and verify
the migration and run the PostgreSQL quota tests before setting
`CLAIM_TRELLIS_HOSTED_PROVIDER_ENABLED=true`. A missing key or secret fails closed.
Turnstile/CAPTCHA for anonymous signup and operational abuse monitoring remain launch
blockers for broad promotion. See [privacy](docs/PRIVACY.md) and [security](SECURITY.md)
before hosting user content.

## Seed literature benchmark

`benchmarks/literature_seed.jsonl` contains English cases derived from recent
(2022–2026) articles in high-authority journals including *Nature*, *Science*, *The New
England Journal of Medicine*, and *JAMA*. The repository stores metadata and concise
editor-authored paraphrases, not publisher PDFs. It is a smoke-test seed, not evidence of
clinical validity. See [the literature policy](docs/LITERATURE_POLICY.md) and
[evaluation protocol](docs/EVALUATION_PROTOCOL.md).

## Repository map

```text
src/claim_trellis/   Core engine, API, CLI, storage, and Jev adapter
web/                    Dependency-free review interface served by the API
tests/                  Deterministic unit and integration tests
benchmarks/             Schemas and recent authoritative literature seed cases
docs/                   Trust, architecture, evaluation, privacy, and threat model
.github/workflows/      Secret-free CI
```

## Security and privacy

Documents may be confidential or copyrighted. ClaimTrellis defaults to local parsing,
local persistence, and no telemetry. Hosted anonymous mode persists the selected evidence,
audit, feedback, block locator/hash manifests and provenance in PostgreSQL, but not raw
upload bytes or an additional full parsed-source copy. Candidate and selected passages
can contain all text of a short source. When the Jev adapter is enabled, the claim,
selected evidence set, and citation context are sent to TypeSafe. Revisions also transmit
human feedback, previous judgment, and deterministic-check context. Review provider terms and institutional policy
before processing unpublished or protected material. See [SECURITY.md](SECURITY.md) and
[docs/PRIVACY.md](docs/PRIVACY.md). The initial dependency and source review is recorded in
[docs/DEPENDENCY_PROVENANCE.md](docs/DEPENDENCY_PROVENANCE.md).

## Status

Alpha. The architecture and deterministic test suite are suitable for open development;
the included thresholds are conservative placeholders and are not validated for clinical,
legal, regulatory, or publication decisions.

## License

Apache-2.0. Contributors retain copyright and certify contributions under the
[Developer Certificate of Origin](DCO.md); no CLA is required.
