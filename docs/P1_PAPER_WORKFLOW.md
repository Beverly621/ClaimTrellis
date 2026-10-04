# Paper Workflow: stage contracts and human acceptance

P0 and P1.1–P1.3 were accepted on 2026-10-03 (PRs #20–#23 merged). P1.4–P1.5 were
merged as PR #24; the owner subsequently reported human real-paper/live-Jev acceptance.
P1.6/P1.7 are now authorized in one new PR, with merge/deployment after green checks.
P1 — Paper Workflow accepted 2026-10-03 (engineering scope; see separate scientific gates).
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
Use a local/disposable database for acceptance. An existing Vercel integration may
create a PR preview automatically; it can still point at the hosted database. Do not
apply a production migration merely to make a preview's new endpoints work. This work
does not change deployment configuration or apply production migrations.

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

## P1.3 — Bibliography/source identity mapping

Only numeric/author-year references, uploaded TXT/MD/PDF/DOCX source collections,
machine suggestions and explicit human identity confirmation. No scraping or GROBID
runtime dependency. Several sources per claim remain separate links, not one verdict.

POST `/{project}/manuscripts/{manuscript}/parse-references` recognizes an explicit
References/Bibliography heading and numeric entry starts (`[12]`, `12.`, `12)`) or
conservative surname/initial/year starts. Continuation lines retain their exact offsets;
a recognized Markdown/Appendix heading ends the bibliography. References retain raw
text, spans, hash, parser version and tentative title/first-author/year/DOI metadata.
Metadata is incomplete and heuristic: layouts that do not match require manual
`ReferenceCreate` spans, metadata and markers. No external paper metadata is fetched.
Parser output is not proof of identity or a comprehensive bibliography extraction result.

POST `/{project}/sources` accepts multipart `document`, `idempotency_key` and optional
`metadata` (JSON string: title, authors, journal, year, doi, access_tier). It reuses the
existing byte/character limits, signatures and TXT/MD/PDF/DOCX parsers; parsing runs in
a threadpool after the owner/project check. Normalized text, grounded blocks, parser
version, warnings and document hash persist, not the original file. Metadata cannot
set owner IDs or content hashes. Replaying the same upload/metadata returns one source;
changed content under the same key conflicts. List/get use `/{project}/sources`.

POST `/{project}/candidates/{candidate}/suggest-mappings` requires a human-confirmed
candidate. Numeric keys expand bounded lists/ranges; author-year keys use first surname,
year and suffix. Duplicate keys remain ambiguous. DOI matches or normalized title
matches (at least three words) propose pending links; conflicting known DOIs never fall
back to title. Supplied metadata is untrusted: a match is only a suggestion. No match
produces a pending unmapped link; unknown citation keys produce warnings rather than
guessed identity. All matching reference/source possibilities remain available for review.
Suggestions are bounded to 200 expanded keys, 2,000 project references, 500 uploaded
sources and 500 links per operation. Exceeding a bound fails atomically, not by truncation.
Source matching reads only identity metadata, not the entire source collection's text.

Manual `SourceLinkCreate` may specify a candidate, a same-manuscript reference and an
optional uploaded source ID. POST `/{project}/source-links/{link}/decisions` requires
confirm/reject, expected revision, idempotency key, reviewer and notes. Confirm additionally
requires a selected same-project source and `identity_confirmed: true`. A reviewer may
correct the machine's source selection; events preserve previous/selected source IDs,
source hash, reference hash and candidate hash/revision. Only pending links are decided;
stale/repeated conflicting requests return 409. Replays do not undo decisions.

### Manual P1.3 acceptance

1. Create a manuscript containing an in-text `[12]` and an explicit reference entry:
   `[12] Smith, J. (2024). Example paper title. Example Journal. doi:10.1234/demo.`
   This is synthetic test data, not a real-paper benchmark.
2. Extract and human-confirm its claim; parse references twice. Check stable IDs, exact
   raw reference text/span/hash and no duplicated events. Repeat with an author-year
   in-text citation and an unnumbered author-year entry.
3. Upload a source you are authorized to use, supplying its actual title/year/DOI metadata.
   Check text/hash/blocks/format locators and identical upload replay.
4. Request suggestions. Every new link is pending. Review the reference and source title
   page yourself; Confirm with the selected source ID and `identity_confirmed: true`, or
   Reject. Supplied DOI alone is not evidence that the uploaded content is that paper.
5. Try a source ID from a different project or owner: verify 404 and no decision event.
   Try confirming without the identity attestation: verify 422.
6. Test two references/two sources for one claim and ambiguous/missing mappings. Confirm
   links independently. Verify project events and that no ClaimAudit was started.

Automated tests cover both database adapters, numeric/author-year styles, bounded marker
expansion, multiline bibliography spans, metadata conflicts, ambiguity, missing sources,
manual mapping, source formats, human gates, stale/concurrent decisions, replay, P1.1
serialized-default compatibility and API prototype flows. These are software contract
tests with synthetic data, not real-literature validation or a held-out accuracy benchmark.

## Separate scientific and adoption gates

P1.6/P1.7 are covered below. Formal independently annotated retrieval data, production
dense adoption and P2 are separate owner gates. No scientific performance conclusion
is justified by workflow tests, synthetic retrieval scores or live integration smoke.

## P1.4 — Ordinary audit orchestration (accepted contract)

Run creation plans only. Each execute request processes one persisted item, by reusing
the existing P0 `run_audit()` and ordinary ClaimAudit persistence. All claims/mappings
must be confirmed with a matching historical human identity decision. Immutable input
snapshots preserve claim text/revision and candidate/reference/source/parser hashes.
One source link has one current initial audit; later semantic re-evaluation uses ordinary
Audit Revision, never an unbounded sequence of duplicate initial audits.

Database leases fence concurrent execution. Completed items replay the same audit ID.
Cached provider results/errors and full audit checkpoints allow safe persistence recovery
without another model call. If an interrupted external call has no durable outcome, fail
closed as `provider_outcome_unknown`; no automatic double-charge retry is claimed.
Provider errors that P0 turns into a valid fail-closed audit finish the item normally.

Paper daily/user, project/run and provider concurrency budgets are explicit configuration
with no new cost-bearing numeric defaults. Preflight is an estimate, not a reservation;
each real model call atomically reserves in the database. Existing hosted IP protections
remain enforced. Deterministic-only execution is an explicit mode, not a hidden fallback.

## P1.5 — Matrix and browser workflow (accepted contract)

The Matrix is an owner/project-scoped projection, not a stored judgment. Each mapping
has its own stable row and ordinary audit link; workflow states remain separate from raw
provider relation, policy status and human decision. Counts are workflow counts, not a
paper score. The browser reuses the ordinary Evidence Console, review and revision APIs.
Queue execution is bounded, refresh/resume uses persisted state, and identity changes
clear project content and invalidate late responses. No bulk Accept/Reject controls.

### API / persistence boundaries

Under `/api/v1/projects/{project}`:

- `POST /audit-runs`: a content-aware idempotent plan for 1–200 selected links only.
- `GET /audit-runs`, `GET /audit-runs/{run}`: persisted membership, item status and live
  preflight. Run status is derived from its items, not a semantic verdict. Reading run
  state recovers expired leases to an explicit failed/unknown state.
- `POST /audit-runs/{run}/items/{item}/execute`: one ordinary audit at most, requiring
  `idempotency_key` and the original `input_snapshot_hash`.
- `GET /matrix?limit=100&offset=0`: read-only stable rows, complete-project workflow
  counts and paginated rows; no model call, human decision or new judgment record.

The canonical item is shared when another plan selects the same source link. Changing
its initial input or provider mode conflicts; later re-evaluation uses P0 Revision.
Audit + versions/events + ProjectAuditLink + item completion commit atomically. Provider
outcomes and the ordinary-audit recovery checkpoint commit before that transaction.
Safe storage retries are bounded to three attempts; completed audits, semantic results,
and unknown provider outcomes are never automatically re-evaluated. Execution keys are
bounded to 200 per item; reuse a key rather than creating unlimited retries. P0's existing
2,000-character citation bound applies; the full original reference/hash remains in the
project record and input snapshot. No raw provider error body is stored by orchestration.

SQLite adds orchestration tables in the existing local database. PostgreSQL requires
`0005_paper_runs.sql` after `0004`, with RLS and no `anon`/`authenticated` grants. **Do not
apply either migration to production just to make a PR preview work.** PR #24 supplied
migration code and disposable-database contract tests, not production
approval or the P1.7 operator migration rehearsal. P1.7 separately rehearses through
0005 on disposable databases as documented below; it authorizes no new production migration.

### Operator choices (not enabled by this PR)

All three settings default to `None` / unconfigured:

| Server-only setting | Meaning |
| --- | --- |
| `CLAIM_TRELLIS_PAPER_DAILY_USER_LIMIT` | Calls per owner over rolling 24 hours |
| `CLAIM_TRELLIS_PAPER_RUN_PROVIDER_LIMIT` | Provider calls charged to one run |
| `CLAIM_TRELLIS_PAPER_MAX_CONCURRENT_PROVIDER_CALLS` | Global in-flight paper provider reservations |

Configure them only after owner cost review. Preflight is an estimate; each actual
provider evaluation is reserved atomically. In hosted mode it also reserves the existing
usage ledger in the same transaction, checks the configured paper-user budget across
hosted usage, and preserves the existing IP limit of 10 and ordinary Revision limit of 5.
The standalone audit's `USER_LIMIT = 7` is unchanged. Configuring paper budgets does not
enable the hosted-provider flag or supply a key/IP secret. Failed/unknown calls consume
budget; an unknown result is not refunded. P0 transport retries remain in its provider.

### P1.4 / P1.5 test checklist and human acceptance

Automated software tests (synthetic fixtures / stub providers only):

- Both SQLite and real disposable PostgreSQL: owner/run scoping, human claim/identity
  gates, immutable source snapshots, one/multi-source ordinary audits, plan and execution
  replay, concurrent execution, transactional rollback and checkpoint recovery.
- Explicit unconfigured/partial/concurrent budgets; atomic hosted IP reservation;
  provider error -> completed fail-closed ordinary audit; interrupted/unknown outcome
  -> no second call; expired global lease recovery; all six relation labels finish without
  semantic retry; safe retry bounds; existing P0 human review and Revision projection.
- Deterministic read-only Matrix, stable multi-source row IDs, pagination/counts,
  raw relation != policy result, accepted/rejected/deferred/revision states and stale CAS.
- Browser rendering: HTML escaping, table headers/native labeled controls, bounded
  queue/partial stop, pagination, existing audit links, signed-out no-fetch, account change
  clearing and stale response suppression. Existing Evidence Console tests remain green.
- Synthetic HTTP component fixture: 3 confirmed claims, 4 confirmed source links and
  1 unmapped -> 4 independent ordinary audits, each with ordinary event history.

Local browser component smoke on 2026-10-03 used **no Jev key**: uploaded synthetic TXT
manuscript/sources; confirmed three claim rubrics and four identities; planned without
execution; executed four deterministic-only audits with the two-worker queue; opened
the existing Evidence Console; recorded one synthetic Defer; returned to the same project;
refreshed and filtered the persisted Matrix. This is not human product acceptance, live
Jev validation, literature evaluation, a held-out benchmark, or P1.7 full E2E completion.

Before merging, the owner should repeat on a local/disposable database:

1. One confirmed claim/two confirmed sources -> two independently reviewable ordinary
   audits and project events containing both IDs. Confirm no automatic acceptance.
2. Keep a candidate or mapping pending/rejected, leave a source missing, then exhaust a
   test-only configured budget: no silent audit, explicit blocked/failed item state.
3. Three claims/four confirmed links/one unmapped -> separate Matrix rows. Inspect each
   uploaded source, selected evidence, ordinary audit, human decision and event history;
   return/refresh and ensure identities and decisions persist.
4. Simulate two browsers' stale decision, logout and account switch. Confirm state clears,
   stale decisions conflict, and no old-owner text or pending request enters the new view.
5. Approve cost-bearing quota values and a separate production backup/migration plan
   only if/when deployment is authorized. The subsequent P1.6/P1.7 authorization does
   not authorize additional production migrations.

## P1.6 — Independent retrieval lab

`experiments/retrieval/` and `benchmarks/retrieval/` are outside production. Frozen
corpus/query/qrels/manifest files plus licensed normalized source snapshots validate
exact production-v2 spans, unique IDs/hashes, canonical paper identities and source-disjoint
dev/test. Formal queries require human atomic-claim confirmation; qrels require two
independent reviewers/adjudication. No supplied real-paper qrels are assumed to exist.
Synthetic data requires explicit opt-in and is never promoted to human labels.

The [recorded ablation report](retrieval-ablation-report.md) publishes only invented,
licensed engineering fixtures and clean-code provenance. It does not satisfy the
separate real-paper human annotation or dense-production adoption gates.

Lexical calls the frozen production retriever; CPU dense searches the same identified
source pool; hybrid sums reciprocal ranks, never raw score spaces. Model/revision,
distance/index settings, top-k/RRF-k, data/split hashes, code SHA/dirty state, parser/chunk/
retrieval versions, package/runtime versions, truncation, resource usage and local cost
limitations are recorded. Report Recall@1/5/10, MRR@10, nDCG@10 and seven hard-negative
slices; missing slices are null. Dense dependencies are `retrieval-lab` extras only.
See [the lab](../experiments/retrieval/README.md) and the ablation report.

Completing this lab is not an adoption decision. Production stays `lexical-evidence-v2`.
Formal held-out labels, gain/regression/cost review, explicit owner approval and a
separate `retrieval-v3 adoption PR` are mandatory before adopting dense retrieval.

## P1.7 — Acceptance, not new algorithms

Frozen versions and code/question hashes are in `P1_ACCEPTANCE_FREEZE.json`; tests reject
changes unless a blocker receives explicit review. Legal invented numeric/author-year
manuscripts exercise actual browser/HTTP/PostgreSQL flows through human Confirm/Edit/
Reject, source identity, separate audits, Matrix, evidence correction, revision and final
decision. Test reviewer actions are simulated, not statements that a human reviewed the
invented scientific claims. Separate-account access is denied and logout/session changes
clear content; actual Supabase and Jev use explicit mocks in browser tests.

The complete contract suite covers ambiguous/unmapped/wrong sources, multiple sources,
timeouts/errors/invalid answers, quota exhaustion, interruption recovery, stale decisions
and concurrency. The trace checker verifies every Matrix join, manuscript/reference
exact span, edited claim, identity reviewer, source/candidate/evidence hash, checks, raw
Jev/model/questions, policy rationale, proposal history and final human action. A broken
join fails the gate. Fresh and existing-0003 disposable databases rehearse through **0005**,
plus pre-upgrade backup restore, idempotency, RLS and owner isolation. No production
migration occurs as a result of this stage.

Opt-in live smoke creates two invented hosted audits to verify real authentication,
Jev v3 answer validation, requested/resolved model, usage and persistence; paid timeout
fault injection is not performed. It cannot accept proposals or claim scientific accuracy.
See [the acceptance record and complete test matrix](P1_ACCEPTANCE.md).

## Conceptual references (no code or dataset imported)

- [SciFact](https://github.com/allenai/scifact): claim/citance/evidence relationships.
- [Scientific Claim Generation](https://github.com/allenai/scientific-claim-generation):
  human atomicity, faithfulness and decontextualization rubric.
- [S2ORC](https://github.com/allenai/s2orc): parsed text, metadata and bibliography linkage.
- [GROBID](https://grobid.readthedocs.io/en/latest/Introduction/): scholarly representation,
  not a new runtime dependency.
