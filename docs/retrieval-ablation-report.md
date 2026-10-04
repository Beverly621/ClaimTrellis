# Retrieval ablation report — synthetic engineering only

Recorded 2026-10-03 (owner timezone). **Production stays `lexical-evidence-v2`.**
No dense adoption or scientific accuracy conclusion follows from this experiment.

## Frozen experiment

Complete run records: [dev](../benchmarks/retrieval/reports/synthetic-dev-v1.json) and
[test](../benchmarks/retrieval/reports/synthetic-test-v1.json). These contain only
invented fixtures licensed under the existing repository license, not private papers,
human labels, credentials or production audit records.

- Dataset: `synthetic-hard-negatives-v1`, 14 invented sources / 168 passages / 14 queries.
  Each source has 12 production-v2 expanded context spans; each split has 7 independent
  sources/queries and one positive qrel per query. Sources and canonical work IDs do not
  cross splits. These are not human-confirmed atomic claims or real-paper held-out labels.
- Clean experiment code SHA: `b1b70038bad8dbfd0d7198837d50f5cd451555d5`.
  Both runs record `working_tree_dirty: false`.
- Split hash: `5a2847bb98d4cffa918f4e7ff9e74ee5009461ad706611671cfe769f7609e322`.
  The records include frozen hashes of sources/corpus/queries/qrels.
- Parser: `structured-document-v2`; retrieval: `lexical-evidence-v2`; chunking:
  `production-v2-context-spans-target900-max1600`. All baselines search the same
  identified source, not a cross-paper discovery corpus.
- Dense: `sentence-transformers/all-MiniLM-L6-v2`, revision
  `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, CPU, cosine distance, L2-normalized
  exact-flat float64 vectors. Input limit 256 wordpieces; zero truncated inputs here.
- Retrieval depth: 10; RRF constant: 60, equal rank contributions. No BM25/cosine score
  blending and no task-specific fine-tuning. MRR is explicitly MRR@10, not unbounded MRR.
- Runtime: Python 3.11.15, macOS arm64; sentence-transformers 5.7.0, torch 2.14.1,
  transformers 5.18.0, numpy 2.4.6. These are optional local experiment dependencies,
  not new production runtime requirements.

## Results and limits

Both tiny synthetic splits returned the same aggregate retrieval metrics:

| Baseline | Recall@1 | Recall@5 | Recall@10 | MRR@10 | nDCG@10 |
|---|---:|---:|---:|---:|---:|
| lexical-evidence-v2 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| dense experimental | 0.8571 | 1.0000 | 1.0000 | 0.9286 | 0.9473 |
| hybrid RRF experimental | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |

No gains over lexical v2 occurred in this sample. Dense ranked the numeric-mismatch
negative above the positive in `query-dev-3` and `query-test-3`; RRF retained the positive
at rank one. The other six slices (population, outcome, direction, causal, timeframe,
same terminology / wrong study) had identical rank-one positive retrieval for all three
baselines. Each slice has only one query per split: this is not a statistical comparison.

All seven slices for every baseline had hard-negative exposure@5 = 1.0: a tagged
negative was present in the retrieved top five. Retrieval is candidate selection, not
a judgment that those candidates support the claim. **This number is not a false-support
rate**, and rank-one positive retrieval is not evidence of scientifically safe judgment.
Every slice's Recall/MRR/nDCG and per-query ranks are in the linked records. These toy
scores validate the harness and identify a regression, not generalization or deployment merit.

## Resources and cost

| Split | Lexical p50 / p95 ms | Dense p50 / p95 ms | RRF p50 / p95 ms | Model load s | Index build s | Peak RSS bytes |
|---|---:|---:|---:|---:|---:|---:|
| dev | 0.490 / 0.769 | 2.815 / 3.500 | 3.413 / 3.448 | 4.205 | 0.617 | 610697216 |
| test | 0.517 / 0.769 | 2.935 / 3.463 | 3.271 / 3.410 | 3.588 | 0.517 | 614514688 |

Each run's dense logical index is 516,096 bytes; persisted index disk size is zero.
RSS includes the interpreter/model. Model load was from the local cache, not a cold
network download. Lexical per-query timing includes its production chunk/rank preparation;
the shared dataset validation is outside query timing. These are one serial CPU pass on
seven queries, not a production SLA, confidence interval or load test.

External embedding API calls/cost: zero / $0. Local hardware cost is unmeasured, not free.
No Jev calls were made by the retrieval experiment. The separately documented live Jev
smoke is an integration check, not part of these retrieval metrics.

## Adoption decision

**Not authorized.** Keep production lexical v2. Before considering adoption, supply
licensed real-paper source-disjoint dev/test data with human-confirmed atomic claims,
two independent qrel annotators and adjudication; freeze provenance; compare gains,
regressions, negative slices, truncation, resources and cost on an untouched test set.
Then obtain explicit owner approval and open a separate retrieval-v3 adoption PR.
P1 engineering acceptance does not substitute for this gate.
