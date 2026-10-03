# Paper Workflow: stage contracts and human acceptance

P0 was accepted on 2026-10-03. Only P1.1, P1.2 and P1.3 are authorized, each in its
own stacked PR and held for human acceptance. This backend prototype is not complete P1.
No new `PaperVerdict`, paper score, provider, dependency or CLI command is introduced.

## P1.1 — Contracts and persistence

`ResearchProject` owns immutable `Manuscript` records, `ClaimCandidate` records and
`ReferenceEntry` records. Pending `ClaimSourceLink` records refer to a candidate and
reference from the same manuscript. `ProjectAuditLink` is a reserved storage contract
for an existing, owned ordinary ClaimAudit, not an audit creation route. Nothing in
this stage changes the frozen judgment core or provider execution.

The REST collection is `/api/v1/projects`. Create requests require an
`idempotency_key` (8–200 characters). IDs are deterministic per owner/project/parent
scope. Same key + same content returns the stored record; different content conflicts.
Creation and its event commit together. Foreign owner, project or parent lookups return
404. List endpoints are paginated (`limit` 1–200, `offset` >= 0).

Manuscripts accept normalized text and optional grounded parser blocks from the existing
`/api/v1/documents/parse` response. Offsets refer to Unicode characters in exactly that
normalized text, not original PDF byte positions. A candidate's `original_span` is not
the later human `confirmed_claim`; both identities must remain separate.

PostgreSQL requires the additive `0004_paper_workflow.sql` migration using the existing
migration CLI. Do not apply it to production until an operator approves the PR and
backup/migration plan. SQLite creates only additive tables in its existing audit DB.
Project text is persisted: read [privacy](PRIVACY.md) before uploading material.

### Manual P1.1 acceptance

1. Run `claim-trellis serve` without a provider key. Open `/docs`.
2. POST `/api/v1/projects` with `{"name":"Demo","idempotency_key":"demo-project"}`.
3. Create a manuscript with filename, normalized text and `idempotency_key`; replay the
   same payload and verify the same ID and one creation event.
4. Change text while retaining its key: verify 409 and no extra event.
5. In hosted test mode, repeat reads with a second authenticated identity: verify 404.
6. Verify an existing ordinary audit can still be created/reviewed through its old routes.

Automated tests exercise all six contracts, both database adapters, owner/project/
manuscript isolation, simultaneous creation, payload conflicts, hash/span grounding,
transaction rollback, authentication and the existing ClaimAudit suite.

## P1.2 — Exact-span extraction and human decisions (next)

Only citation-bearing sentences and conservative original clause spans, followed by
human Confirm/Edit/Reject. Never generate or insert a missing subject automatically.
Acceptance requires Atomicity, Faithfulness and Necessary Context checks.

## P1.3 — Bibliography/source identity mapping (next)

Only numeric/author-year references, uploaded TXT/MD/PDF/DOCX source collections,
machine suggestions and explicit human identity confirmation. No scraping or GROBID
runtime dependency. Several sources per claim remain separate links, not one verdict.

## Deferred

P1.4 audit fan-out/idempotency/retry/quota, P1.5 Matrix, P1.6 dense/hybrid/RRF/offline
benchmark and P1.7 end-to-end/live-Jev acceptance require separate authorization.
No performance conclusion is justified by the workflow contract tests.

## Conceptual references (no code or dataset imported)

- [SciFact](https://github.com/allenai/scifact): claim/citance/evidence relationships.
- [Scientific Claim Generation](https://github.com/allenai/scientific-claim-generation):
  human atomicity, faithfulness and decontextualization rubric.
- [S2ORC](https://github.com/allenai/s2orc): parsed text, metadata and bibliography linkage.
- [GROBID](https://grobid.readthedocs.io/en/latest/Introduction/): scholarly representation,
  not a new runtime dependency.
