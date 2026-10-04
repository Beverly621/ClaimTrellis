# Changelog

All notable changes will be documented here.

## 0.1.0 - Unreleased

- P1.6: independent frozen source-disjoint offline retrieval harness, production-v2
  lexical adapter, optional pinned CPU dense adapter, RRF, recall/MRR/nDCG, seven
  hard-negative slices and reproducible provenance/resource reports. Synthetic fixtures
  are engineering regression only; formal human labels and production adoption remain
  separate gates. Production retrieval, provider architecture, API/CLI and six labels unchanged.
- P1.7: algorithm/contract hash freeze, numeric and author-year Chromium E2E with
  original spans, human gates, ordinary audit/revision, Matrix, session restoration,
  owner isolation and full trace assertions; disposable PostgreSQL fresh/upgrade and
  backup/restore rehearsals; opt-in two-case live integration smoke and acceptance docs.
- Owner-requested small UI adjustment: equal hero entry sizes, 📮 Sign in icon, no
  hero/header entry arrows, and removed hero eyebrow text/divider. Authentication unchanged.
- P1.4–P1.5: persisted run/item orchestration, idempotency, quota/recovery checkpoints,
  per-source ordinary audits and browser Review Queue / Evidence Matrix. The owner
  reported real-paper/live-Jev acceptance on 2026-10-03 after PR #24 merge/deployment.

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
  Accepted 2026-10-03; this stage alone starts no audit execution or new UI.

- P0 Core Audit Fidelity v2: structured source blocks, bounded Top-K lexical retrieval,
  multi-passage evidence sets, human evidence correction with immutable snapshots,
  deterministic checks v2, independent Jev scientific dimensions v3, fail-closed policy v2,
  detailed provenance/events and regression fixtures. CLI commands, providers and six
  relation labels remain unchanged; P2 is not implemented.
- Initial deterministic evidence pipeline, Jev adapter, policy engine, REST API, CLI,
  human review UI, local audit store, evaluation harness, and curated literature seed.
