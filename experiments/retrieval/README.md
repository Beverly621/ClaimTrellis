# Offline retrieval lab — no production adoption

Production remains `lexical-evidence-v2`. Nothing in this directory is imported by
the service, packaged in the wheel, or added to the product CLI. Optional installation:

```sh
python -m pip install -e '.[dev,retrieval-lab]'
python -m experiments.retrieval.run benchmarks/retrieval/synthetic \
  --allow-synthetic --split dev \
  --revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41 \
  --output benchmarks/results/dev-run-001
```

Use a new output directory for every run. A test run changes `--split test`; never
tune on held-out labels. `run.json` records hashes, pinned revision, package/runtime
versions, code SHA/dirty status, exact index settings, truncation, top-k and RRF k.
`retrieval-ablation-report.md` records gains/regressions, costs and adoption gates.

## Dataset contract

The BEIR-shaped core is `corpus.jsonl`, `queries.jsonl`, `qrels.tsv`, `manifest.json`.
`sources.jsonl` additionally holds licensed normalized source snapshots and blocks so
the harness can verify every exact span and call the *actual production* v2 retrieval
function. The fixed corpus must contain exactly its expanded context spans. A
source-qualified production passage ID is `_id` (avoids identical-content ID collisions).

All three baselines search **within the same identified source**, matching P0's
claim-plus-one-source boundary. This is not cross-paper source discovery. Dense uses
the same corpus, exact cosine search, CPU, no remote code; hybrid uses equal rank
contributions `sum(1/(60+rank))`, not blended BM25/cosine scores. Hybrid branch depth
is the reported top-k. MRR is explicitly truncated at 10, as are nDCG@10 results.
Recall divides retrieved relevant passages by all annotated relevant passages, not
by the number of returned passages. Unjudged passages receive gain zero; annotation
completeness remains a human responsibility.

Each source has a canonical `work_id` shared by versions of the same paper, preferably
a normalized DOI. Both work identity and identical source hashes must be disjoint
between dev/test. Keep parser/retrieval versions and file hashes frozen. Formal
datasets require two named independent qrel reviewers and an adjudicator, and every
query must attest human atomic-claim confirmation and a reviewer. These fields record
human attestations; software cannot verify that people really performed the annotation.
The loader rejects leakage, bad spans/hashes, duplicate/foreign qrels, empty relevance,
and hard-negative IDs without explicit zero-grade qrels.

`synthetic` is deliberately **not** human-confirmed. It requires `--allow-synthetic`,
contains seven tagged hard-negative slices, and validates mechanics only. Missing
slices are null, not passing. Hard-negative retrieval is not a false-support judgment.
Keep private papers, tokens, embeddings and individual rankings under ignored paths;
publish only licensed data or sanitized aggregates with owner approval.

## Sources and adoption

Dataset IDs/qrels follow [BEIR's loader format](https://github.com/beir-cellar/beir/blob/main/beir/datasets/data_loader.py).
Rank fusion follows the [Haystack DocumentJoiner RRF pattern](https://docs.haystack.deepset.ai/docs/documentjoiner),
without adding either framework. The CPU experiment uses the
[all-MiniLM-L6-v2 model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)
and [SentenceTransformer revision API](https://sbert.net/docs/package_reference/sentence_transformer/model.html).
The model has a 256-wordpiece limit: report truncation, do not silently call it a
scientific full-passage encoder. No task-specific fine-tuning is performed.

Require a formal source-disjoint human-adjudicated benchmark, gains/regressions and
cost review, owner approval, and a **separate retrieval-v3 adoption PR**. This harness
has no route or configuration that can enable dense production retrieval.
