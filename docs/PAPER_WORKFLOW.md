# Paper Workflow

Paper Workflow organizes manuscripts, human-confirmed claims, uploaded sources and
ordinary ClaimAudits. Open `/projects` to use the Review Queue and Evidence Matrix.
It does not produce a paper verdict, paper-quality score or automatic peer review.

## Review a manuscript

1. Create a research project and upload an English TXT, Markdown, PDF or DOCX manuscript.
2. Extract citation-bearing claim candidates. Each candidate preserves its exact span
   in normalized manuscript text, offsets, grounded locator and content hash.
3. Confirm, edit or reject each candidate. Confirm/Edit require human attestations for
   atomicity, faithfulness and necessary context. Machine extraction does not invent
   missing subjects or make a claim final. An edited claim and the original span remain
   separate records; extraction never overwrites existing human decisions.
4. Parse bibliography entries and upload the corresponding lawful source files. Title,
   DOI and year matches suggest possible associations; they are not identity proof.
5. Inspect each association and explicitly confirm the source identity or reject it.
   A claim may link to several sources, each with its own independent identity decision.
   Ambiguous or unmapped references remain unresolved until a reviewer acts.

## Execute and review

Plan an audit run for confirmed claim/source links. Planning shows readiness and quota
without calling a provider. Execution requires a confirmed claim, a confirmed source
identity and an explicitly selected execution mode. Unready links remain blocked.

Every ready pair enters the existing ClaimAudit pipeline: lexical evidence retrieval,
deterministic checks, optional structured provider judgment, fail-closed policy and
human review. A deterministic-only audit cannot establish semantic support. Provider
evaluation requires configured credentials and available quota.

Run items checkpoint immutable input snapshots and typed outcomes. Retry/resume use the
same run/item identities, idempotency keys and transactional reservations rather than
creating duplicate audits. Provider errors, exhausted quota and interrupted execution
remain visible operational states, not scientific verdicts. Recovery does not bypass
identity gates or silently re-execute a completed item.

The Evidence Matrix separates raw provider relation, policy proposal, run status and
human decision. Open a completed cell in the ordinary audit console to inspect evidence,
accept/reject/defer/revise, or request an evidence correction. A correction creates a new
immutable proposal and evidence snapshot; prior judgments and reviews remain auditable.
Stale or concurrent human decisions are rejected instead of overwriting newer state.

## Traceability and access

A completed cell links the original manuscript span, confirmed claim, bibliography
entry, source identity reviewer, uploaded source hash, retrieved candidates, selected
evidence, deterministic checks, provider/question/model provenance, policy reasons,
final human decision and revisions through append-only events. Legacy audit records
without newer provenance remain explicitly identifiable rather than reconstructed.

Hosted records are scoped to the authenticated owner, including every child lookup.
Logging out or changing accounts clears the browser's current view. Linking an account
preserves an existing guest identity; switching identities does not merge histories.

## Limits

Production retrieval remains `lexical-evidence-v2`. The independent dense/RRF lab does
not change it. Workflow integration tests and live-provider smoke tests are not an
accuracy benchmark, scientific validation, autonomous fact checking or permission to
process protected material. Formal evaluation needs independently adjudicated,
source-disjoint held-out data. See [trust](TRUST_SPEC.md), [evaluation](EVALUATION_PROTOCOL.md)
and [privacy/retention](PRIVACY.md) before using real research content.
