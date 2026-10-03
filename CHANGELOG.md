# Changelog

All notable changes will be documented here.

## 0.1.0 - Unreleased

- P1.3: heuristic numeric/author-year bibliography entries with exact spans, independent
  uploaded source collections (the existing TXT/MD/PDF/DOCX parser), metadata-only mapping
  suggestions, unresolved/ambiguous mapping warnings, and human source-identity decisions.
  No automatic audits, Paper Matrix, scraping, live Jev or retrieval experiments.

- P1.2: deterministic citation-bearing sentence / conservative exact-span suggestions
  and human Confirm/Edit/Reject with a three-part rubric, original-span preservation,
  stale-state protection, idempotent decisions and append-only review events.

- P1.1 backend contracts: owner-scoped projects, immutable manuscripts, exact-span
  candidates/references, pending source links, reserved existing-audit links, stable
  idempotent creation and transactional append-only events on SQLite/PostgreSQL.
  Human acceptance pending; no automatic audit execution or new UI.

- P0 Core Audit Fidelity v2: structured source blocks, bounded Top-K lexical retrieval,
  multi-passage evidence sets, human evidence correction with immutable snapshots,
  deterministic checks v2, independent Jev scientific dimensions v3, fail-closed policy v2,
  detailed provenance/events and regression fixtures. CLI commands, providers and six
  relation labels remain unchanged; later P1 stages and P2 are not implemented.
- Initial deterministic evidence pipeline, Jev adapter, policy engine, REST API, CLI,
  human review UI, local audit store, evaluation harness, and curated literature seed.
