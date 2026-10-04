# P1 Paper Workflow acceptance

Engineering verification date: 2026-10-03. The owner separately reported completed
P1.5 real-paper/manual acceptance and authorized the P1.6/P1.7 PR, merge after green
checks, and existing Vercel production deployment. Final test/commit evidence is recorded
in the PR. This record is not independent scientific validation.

## Frozen boundaries

[`P1_ACCEPTANCE_FREEZE.json`](P1_ACCEPTANCE_FREEZE.json) freezes paper workflow contracts,
exact-span extraction, bibliography parser, mapping, orchestration, production retrieval,
parser/checks, Jev initial/revision questions, requested model and policy. Code and question
hash tests detect changes. No algorithms, production models, provider/API/CLI contracts,
six relation labels or automatic acceptance are changed. Runtime dependencies are unchanged;
embedding and Chromium tooling are separate optional extras.

## Test matrix

| Gate | Evidence and scope |
|---|---|
| Offline lab | `test_retrieval_lab.py`: frozen generation/hashes, source/work disjointness, exact production context spans, same candidate pool, lexical/dense/RRF, Recall@1/5/10, MRR@10/nDCG@10, seven negative slices, malformed qrels/embeddings, explicit synthetic opt-in |
| Algorithm freeze | `test_acceptance_freeze.py`: production code/question/version hashes unchanged |
| Full browser E2E | `test_p1_browser_e2e.py`: numeric and author-year invented manuscripts; actual Chromium, HTTP and PostgreSQL; simulated human Confirm/Edit/Reject, bibliography, uploads, ambiguous/multi-source/unmapped/wrong-source decisions, planning without calls, ordinary audits, Matrix, review, evidence correction/revision, refresh/persistence |
| Human/session boundaries | Guest sign-out guard, explicit account switch, mocked same-session restoration, cleared private content; second verified mock user denied project/source/audit/Matrix/run access. SDK/auth and Jev are test doubles; actual email/Google sign-in is not simulated as real |
| Traceability | `verify_trace` joins Matrix → manuscript exact span → edited confirmed claim → reference exact span/hash → source-identity event/reviewer → uploaded source/hash → immutable input snapshot → all candidates → selected evidence hash → checks → raw Jev/model/questions → policy rationale → immutable versions → final reviewer/revisions. An intentionally corrupted source hash fails |
| Edge cases and regressions | Existing SQLite/PostgreSQL workflow/run/auth/revision/provider tests: stale CAS, concurrent/replayed requests, interruption/checkpoint recovery, unknown outcomes fail closed, provider timeout/error/invalid answers, quota exhaustion, all six relations, no duplicate paid execution; JS tests stop/drain failed queues and ignore stale account responses |
| PostgreSQL rehearsal | `test_p1_migration_rehearsal.py`: fresh 0001→0005 and existing 0003→0005; synthetic custom-format backup; restoration to another newly created disposable DB; pre-upgrade recovery, repeat migration, retained audit/events, owner isolation, RLS and no anonymous/authenticated grants. No production down-migration, clone or migration |
| Small UI request | Desktop/mobile, Light/Night: equal 240px × 48px hero buttons, 📮 icon, no entry arrows or removed hero text/divider, no horizontal overflow, keyboard dialog entry/focus restoration, zero provider calls |
| Live smoke | Two real hosted audit requests from one independent synthetic Guest; real Supabase authentication and server-side Jev, pinned requested `jev-1.13.0`, resolved `jev-1.13.0`, v3 12-answer validation, usage and persisted records; no human verdict/accuracy scoring |

Live smoke returned **live integration smoke passed** on 2026-10-03 (owner timezone).
The two requests used 4,066 input and 1,226 output tokens in total. A separate read-only
production check verified exactly two succeeded usage reservations with matching token
totals. Retries in these calls: zero. Timeout/retry/invalid-answer fault injection is covered
with mocks, not by intentionally failing paid production calls. Sanitized per-case details
are local and Git-ignored. The throwaway Guest was logged out; synthetic audits remain
under normal retention. Owner sessions, secrets and real-paper records were untouched.

## Repeat the full suite

```sh
python -m pip install -e '.[dev,e2e]'
python -m playwright install chromium
# Supply a disposable PostgreSQL database named claim_trellis_test.
# Its role must be allowed to create/drop only the UUID-named rehearsal test databases.
# pg_dump/pg_restore must be installed. Local Docker fallback requires a container
# labeled claim-trellis.task=p17-acceptance and TEST_PG_CONTAINER with its exact name.
ruff check .
ruff format --check .
mypy
pytest --cov=claim_trellis --cov=experiments --cov-report=term-missing
node --test web/*.test.js
docker build -t claim-trellis-acceptance .
```

CI supplies disposable PostgreSQL 16, installs Chromium and runs browser acceptance.
Local acceptance also ran PostgreSQL 17. A missing browser/PG environment can skip
optional tests; that is **not** full acceptance. Required CI must be green before merge.
Coverage is exercised code, not proof of correctness; it is not a scientific success rate.

Opt-in live smoke, outside the product CLI:

```sh
python -m experiments.acceptance.live_smoke --origin https://www.trellis.ink \
  --allow-hosted-calls --output reports/local/p17-live-NEW.json
```

This creates one ordinary Guest and two invented audits, consumes hosted quota, and
does not bypass guards, change configuration, read a real key or accept a verdict.
Do not use it to repeat paid calls unnecessarily. Do not publish local session records,
environment files, private uploads or credentials.

## Interpretation and remaining human gates

- P1 is an engineering/workflow acceptance, **not scientific accuracy validation**.
- P1 is **not paper-quality scoring**, **automatic peer review** or an **autonomous fact checker**.
- Real-paper retrieval qrels still need two independent human annotators/adjudication.
  Existing manual testing and literature seed are not silently converted to gold labels.
- Synthetic source-disjoint dev/test runs demonstrate reproducibility only, not a
  scientific held-out benchmark. No embedding adoption or false-support claim follows.
- Review formal retrieval gains/regressions, hard negatives, truncation, latency and cost;
  only explicit owner approval and a separate retrieval-v3 adoption PR can change production.
- Hosted Provider remains enabled by the owner's latest instruction. Quotas, keys and
  IP secret are unchanged. Confidential-data retention/deletion policy remains a human gate.
- No production migration is authorized by these rehearsals. No PyPI, formal Release,
  public-visibility change, promotion, brand or license change occurs.
