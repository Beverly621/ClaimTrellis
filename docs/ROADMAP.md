# Core Capability Roadmap

The owner accepted P0 and P1.1–P1.3 and authorized P1.4–P1.5 on 2026-10-03.
P1.6, P1.7 and P2 require separate authorization. The product remains an auditable
claim-to-source verification system with human final judgment.

## P0 — Core Audit Fidelity v2 (accepted 2026-10-03)

Keep TXT, MD, PDF, and DOCX inputs and one atomic claim plus one identified source.
Preserve raw normalized text and compatible legacy fields.

- Structured `DocumentBlock` records with stable IDs, types, offsets, hashes, and
  format-appropriate locators (PDF pages, DOCX paragraphs/sections, Markdown headings,
  TXT line ranges).
- Deterministic Top-K lexical retrieval (default ten), scoring features, de-duplication,
  adjacent context, and bounded sets of one to three source passages. No embeddings.
- Human evidence correction with provenance, immutable proposal versions, append-only
  events, optimistic concurrency, idempotency, and recoverable provider failures.
- Registry-based deterministic quote, numeric, quantity/unit, range, direction,
  comparator, citation, and completeness checks. Ambiguity requires human review.
- Jev question set v3: six existing relations, claim type, population, intervention or
  exposure, comparator, outcome, timeframe, direction, causal fidelity, context
  sufficiency, and prompt injection. Typed results; code-generated explanations.
- Fail-closed policy v2, with automatic acceptance disabled and every final decision human.
- Review UI shows selected source evidence, candidates, structured dimensions, proposal,
  and evidence correction without a chat interface or a visual redesign.
- Version parser, retrieval, checks, questions, policy, requested/resolved model, and
  evidence-set hashes. Prepare offline P0 regression cases and source-grounded literature
  benchmarks; do not claim measured Jev accuracy without a formal held-out evaluation.

## P1 — Paper Workflow (P1.4–P1.5 authorized / active)

The first three backend stages were accepted and merged as PRs #21, #22 and #23.
P1.4–P1.5 use one PR and stop at human acceptance; no automatic merge is authorized.
See [the stage contracts and manual checks](P1_PAPER_WORKFLOW.md).

| Stage | Boundary | Status |
|---|---|---|
| P1.1 | Contracts and SQLite/PostgreSQL persistence | Accepted 2026-10-03 |
| P1.2 | Exact-span extraction and human Confirm/Edit/Reject | Accepted 2026-10-03 |
| P1.3 | Bibliography, uploaded sources, human mapping identity | Accepted 2026-10-03 |
| P1.4 | Ordinary audit orchestration, retries and paper-aware quota | Authorized / Active |
| P1.5 | Review Queue / Paper Evidence Matrix | Authorized / Active |
| P1.6 | Offline dense/hybrid retrieval experiments and benchmarks | Deferred |
| P1.7 | Full workflow E2E, live Jev smoke and final acceptance | Deferred |

The full P1 sequence, not the current implementation, includes:

- Manuscript citation-bearing sentences and conservative clause splitting; humans confirm
  atomic claims and citation/source mapping.
- Research-project manuscript/source organization, many ordinary ClaimAudits, review
  queue, and a Paper Evidence Matrix. No opaque paper-quality score.
- Experiment with lexical, embedding, and hybrid retrieval; compare Recall@1, Recall@5,
  and MRR through ablations before adopting a new retrieval mechanism.

## P2 — Research-grade Verification (deferred)

Only after P1 and separate authorization:

- Shared core plus AI/ML and biomedical domain profiles.
- Explicit statistical quantities (sample size, effects, confidence intervals,
  denominators, and absolute/relative risk), with validated deterministic rules.
- Cross-claim and cross-source consistency, limitations, and conflicting evidence.
- Double annotation and adjudication; calibration on validation data and an untouched,
  source-separated private held-out set.

## Excluded from current work

No new formats, OCR, web scraping, chatbot, summaries, writing/rewriting, automatic source
replacement, paper scores, free-text model explanations, automatic acceptance, new
providers, billing, collaboration, account expansion, or broad homepage/UI redesign.
No dependency upgrades unless needed for a defect or security fix. Publication,
visibility changes, production deployment, and performance claims need separate authority.
