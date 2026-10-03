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

## P1.2 — Exact-span extraction and human decisions

Only citation-bearing sentences and conservative original clause spans, followed by
human Confirm/Edit/Reject. Never generate or insert a missing subject automatically.
Acceptance requires Atomicity, Faithfulness and Necessary Context checks.

POST `/{project}/manuscripts/{manuscript}/extract-candidates` under `/api/v1/projects`
reuses `extract_citation_sentences()`, excludes an explicit References/Bibliography
section, and proposes top-level semicolon/obvious predicate splits. Unknown conjunctions
stay intact; noun lists, parentheses and double-quoted text are not split. Terminal
parenthetical citations are removed only by narrowing the span. Narrative citations
such as `Smith (2024)` stay intact, since removing them could remove the subject.
Candidates are bounded to 2,000 per extraction; overflow fails before any record is saved.

For `Model A improves accuracy and reduces inference time [12].`, the second suggestion
is **`reduces inference time`**, not `Model A reduces inference time`: the latter is not
a contiguous exact span. A human may Edit it; the original span remains immutable.
Extraction is a heuristic suggestion, not a scientific atomicity or citation-scope result.

POST `/{project}/candidates/{candidate}/decisions` requires `decision` (confirm/edit/reject),
`expected_state_revision`, `idempotency_key`, nonblank `reviewer` and `notes`. Confirm
copies the original span; Edit requires `confirmed_claim`; Reject stores no confirmed
claim. Confirm/Edit require `rubric` with `atomic`, `faithful`, `necessary_context` all
true. These are explicit human attestations, not automated correctness scores.
Only a pending candidate can be decided. Stale/concurrent decisions return 409. Replaying
the same decision returns its stored state and no duplicate event. Re-extraction does
not reset any human decisions. The event retains the rubric, both text fields and revision.

### Manual P1.2 acceptance

1. Create the example manuscript above and run `extract-candidates` twice: stable IDs,
   exact original spans and only one creation event per candidate.
2. Edit the second candidate to `Model A reduces inference time`, with all rubric checks.
   Verify both texts in the response and project events. Re-extract: the edit survives.
3. Try confirming without the rubric or using a stale revision: verify 422/409.
4. Reject another candidate; verify no confirmed claim and no provider/audit activity.
5. Review the original sentence yourself for citation scope, atomicity and context.

Automated checks include Unicode offsets, duplicate sentences, citation styles, noun
lists/quotes/parentheses, rubric failures, edit/reject/replay, owner isolation and racing
human decisions on both databases. The browser review UI is intentionally not expanded.

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
