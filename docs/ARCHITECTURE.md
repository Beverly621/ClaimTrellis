# Architecture

## Data flow

```text
uploaded source
  -> local parser
  -> normalized document + source-grounded structured blocks
  -> block-aware deterministic chunking
  -> Top-K lexical candidate retrieval + bounded context + de-duplication
  -> one to three selected source passages
  -> versioned deterministic checks
  -> one provider request with parallel atomic questions
  -> explicit policy proposal
  -> human review
  -> append-only audit record and versioned evidence snapshots

Human evidence corrections use the existing revision lifecycle. Candidate IDs are checked
against the owned audit, then new checks and judgments run against the selected set. Only
a successful transaction advances the proposal and evidence together; failed requests
leave the previous evidence and proposal usable. P0 details and limits are documented in
[Core Audit Fidelity v2](P0_CORE_AUDIT_FIDELITY.md).
```

## Components

- `ingestion.py`: text, Markdown, PDF, and DOCX extraction with upload limits.
- `document_blocks.py`: exact normalized-text spans, locators, hashes and coverage validation.
- `citations.py`: sentence segmentation and citation-marker discovery.
- `chunking.py`: paragraph-aware, overlapping passages with stable locators.
- `retrieval.py`: deterministic BM25-style candidate ranking.
- `deterministic.py`: quote location, normalized hashes, and numeric checks.
- `checks/`: versioned rule registry; findings are not semantic proof.
- `evidence_sets.py`: bounded source-ordered evidence sets and stable hashes.
- `provider.py`: vendor-neutral structured judgment protocol and error boundary.
- `providers/typesafe_jev.py`: default TypeSafe Jev adapter, retries, typed requests, and validation.
- `policy.py`: versioned, fail-closed composition of independent signals.
- `audit.py`: orchestration and provenance construction.
- `storage.py`: SQLite records and append-only event stream.
- `postgres_store.py`: owner-scoped transactional records, quotas and optimistic concurrency.
- `audit_fidelity.py`: evidence revision snapshots and detailed pipeline events.
- `metrics.py`: benchmark and calibration measurements.
- `api.py`: REST boundary and static review interface.
- `cli.py`: local and automation-friendly commands.

## Why retrieval precedes structured judgment

The semantic provider is not used as a long-document search engine. The retriever reduces
the source to short candidate passages; the provider judges each relevant relationship.
Retrieval recall and semantic judgment quality are measured separately. The default Jev
adapter sends independent questions over shared state in one request.

## Why numbers stay in code

Numeric precision, counting, date ordering, and unit conversion are deterministic tasks.
They remain in code because the provider's value is semantic judgment, not arithmetic.

## Deployment profiles

- **Local workstation**: default; SQLite and uploads remain local.
- **Controlled team service**: TLS reverse proxy, encrypted volume, access control,
  retention policy, worker queue, and organization-managed TypeSafe key required.
- **Hosted anonymous workspace**: PostgreSQL, verified Supabase identity and existing
  database-atomic provider reservations; no shared provider key without spend controls.

Hosted persistence is not a clearance to process sensitive research data. P0 changes no
deployment, account, quota or release settings. Additional operational safeguards remain
in the roadmap.
