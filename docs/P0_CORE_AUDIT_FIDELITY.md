# P0 — Core Audit Fidelity v2

P0 improves one atomic English claim against one identified source. TXT, MD, PDF and
DOCX remain the only formats. No embeddings, new provider, batch manuscript workflow,
chat, publication, deployment configuration or P1/P2 work is included.

## Versioned contract

| Component | Version |
|---|---|
| Parser | `structured-document-v2` |
| Retrieval | `lexical-evidence-v2` |
| Deterministic checks | `deterministic-v2` |
| Initial Jev questions | `claim-source-en-v3` |
| Revision Jev questions | `claim-source-revision-en-v3` |
| Policy | `fail-closed-v2` |
| Requested default model | `jev-1.13.0` (unchanged) |

## Parsing and retrieval

The parser preserves existing normalized text and its SHA-256. `blocks` adds stable IDs,
types, offsets, hashes and source-grounded locators: PDF pages, DOCX styled headings and
paragraphs/table rows, Markdown heading hierarchy, or TXT normalized line numbers.
Metadata that a format does not establish stays absent. Failed format grounding falls
back to exact normalized-text offsets with a warning; it never drops source text.
Scanned PDFs still require external OCR; layout, footnote reading order and complex tables
are not guaranteed. DOCX normalization retains its existing paragraph-then-table order.

Requests may omit blocks for compatibility. Supplied blocks must uniquely and completely
cover non-whitespace source text with matching offsets and hashes. A supplied content hash
must match the source. Persisted audits contain only a text-free block manifest, not a
second full-source copy. Candidate passages themselves can cover a short source entirely.

The lexical ranker defaults to ten candidates (existing `top_k` limit remains 1–20),
with term coverage, rare terms, exact phrases, numeric matches, grounded Results/Discussion
headings and explicit citation proximity boosts. It adds bounded adjacent source context,
de-duplicates expanded spans, and uses stable source ordering for ties. These are inspectable
heuristics, not measured retrieval recall. The initial selection uses positive-score,
non-overlapping candidates. Zero-overlap candidates remain available for human inspection
but do not become automatically selected evidence.

An evidence set contains one to three unique passages in source order, at most 8,000
source characters. Its hash includes passage IDs, hashes, locators and offsets. Separate
passages are delimited explicitly in provider state; no synthetic source sentence or quote
is created. `selected_passage` remains the first selected passage for old clients.

## Deterministic findings and Jev

Rule modules cover selected-context quotes, numeric/percent consistency, explicit unit
conversion, range preservation, lexical direction/null conflicts, explicit comparator
presence, citation identity and source completeness. Every finding has an ID, status,
code-authored reason and blocking flag. Percentages are not silently equated with decimal
fractions. Only a small exact metric unit map is supported. Ranges are not scalar equality.
Direction/comparator checks are conservative lexical checks, not scientific inference.
Citation identity and access completeness remain reviewer-confirmed metadata.

Twelve independent questions share the same bounded state in one Jev request: the six
existing questions (scope now focuses on breadth/qualifiers) plus claim type, intervention/
exposure, comparator, outcome, timeframe and direction. All six relation options are
unchanged. Answers must have known options, finite normalized distributions, consistent
selected options and resolved-model metadata; malformed responses fail closed. Revisions
treat human feedback and previous answers as untrusted context, not evidence.

Policy evaluates raw answers separately. A `supports` relation cannot override numeric or
rule conflicts, an outcome/timeframe/comparator/intervention/direction mismatch, uncertainty,
insufficient context or injection signals. Reasons come from code; the model generates no
explanation. `auto_accepted` is always false. Experimental confidence thresholds are not
empirically validated and do not represent probability that a claim is true.

## Human evidence correction

The existing revision endpoint accepts optional `selected_passage_ids` (one to three,
unique, belonging to this owned audit's candidate list), alongside the existing reviewer,
feedback, proposal/version reference, optimistic state revision and idempotency key.

1. Validate selection and ownership before reserving a run.
2. Re-run checks and the configured provider against that evidence set.
3. On success, atomically supersede the prior proposal and persist the new proposal,
   evidence, checks and provenance. Events reference the correct resulting proposal.
4. On provider failure, preserve the prior evidence/proposal. Retrying does not silently
   apply a failed selection; idempotent replay returns the recorded attempt.

Without a provider, explicit evidence correction can still create a deterministic-only
`review_required` proposal. It never simulates a model judgment. Ordinary feedback-only
provider revisions retain their prior unavailable-provider failure behavior.

The review UI shows the selected set, bounded candidate checkboxes, independent dimensions,
check findings, policy disposition distinct from raw relation, provenance and exact
per-version evidence. It requires reviewer/feedback for correction, disallows accepting an
unsaved changed selection and preserves drafts on failure. Legacy versions without evidence
snapshots are identified honestly. This is an extension of the existing interface, not a
redesign or chat workflow.

## Auditability and compatibility

SQLite and PostgreSQL store additive JSON snapshots without a schema migration. New
proposals include evidence sets, checks and provenance; old snapshots remain readable.
CLI command names, endpoint paths, provider abstraction, account/quotas and six relations
remain intact. Some P0 defaults and policies intentionally change: default Top-K is ten,
judgment context is multi-passage, malformed answers are rejected more strictly and support
must pass the additional dimensions/checks. This is not a zero-behavior-change update.
`not_addressed` also routes to review even with full-text metadata: a retrieved set is not
an exhaustive check of every source statement, so source-wide silence is not inferred.

New pipeline events are `document.parsed`, `retrieval.started`, `retrieval.completed`,
`candidate.created`, `evidence.selected`, plus existing checks/judgment/proposal events.
Corrections add `evidence.selection.changed` with old/new IDs/hashes and reviewer. Each
new proposal captures parser, retrieval, checks, question, policy, requested/resolved model
and evidence-set hash. Model-not-run cases say `not-run` and use null model fields.

## Verification and remaining human work

Python regressions cover all four parsers, exact grounding/coverage/hashes, stable Top-K,
quote/unit/range/direction/comparator rules, fine-dimension mismatches, malformed responses,
successful/failed evidence revisions, idempotency, stale reviews and legacy behavior.
Real disposable PostgreSQL tests additionally cover ownership and concurrent updates.
Dependency-free JavaScript tests cover projection, bounds, escaping, accessible passage
IDs, legacy snapshots and policy-vs-relation display. Synthetic regression fixtures and
the existing literature seed are not held-out scientific benchmarks.

Human work remains: independent domain-aware annotation and adjudication, a source-disjoint
frozen held-out set, review of full lawful source context and later measured threshold
calibration. No false-support-rate or clinical/scientific accuracy claim follows from
passing engineering tests. P1/P2 require separate owner authorization.
