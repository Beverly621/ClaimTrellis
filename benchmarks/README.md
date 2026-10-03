# Recent authoritative literature seed

`literature_seed.jsonl` is a small pipeline and schema benchmark. Every case is English,
derives from an original research article published from 2022 through 2026, and points to
a first-party journal page and DOI. Included journals are *Nature*, *Science*, *Nature
Medicine*, *The New England Journal of Medicine*, and *JAMA*.

The `evidence` values are concise editor-authored paraphrases checked against the indicated
abstract or article section on 2026-09-21. They are not publisher text and they do not
replace reading the source. No paper PDF is distributed.

## Important limitation

The seed labels have not yet been double-annotated or independently adjudicated. They are
appropriate for regression tests and question-design experiments, not for an accuracy
claim. Before public benchmark use:

1. appoint two domain-aware annotators;
2. blind them to model predictions;
3. adjudicate disagreements;
4. split by `source_id`;
5. freeze hashes and hold out the test labels.

## Validate

`p0_regression.json` is a separate synthetic engineering fixture, exercised by
`tests/test_audit_fidelity.py`. It covers quote normalization, percent/decimal distinctions,
explicit units, missing units, ranges, direction/null conflicts and comparator absence.
Parsing, retrieval grounding, v3 mismatches, malformed answers and transactional evidence
correction have additional regression tests. These cases are neither held-out literature
nor a measurement of Jev accuracy or false-support rate.

```bash
claim-trellis benchmark validate benchmarks/literature_seed.jsonl
```

Predictions use one JSON object per line:

```json
{"case_id":"af3-supports-molecular-types","prediction":"supports","probabilities":{"supports":0.94,"partially_supports":0.03,"contradicts":0.01,"not_addressed":0.01,"insufficient_context":0.01,"source_unavailable":0.0},"confidence":0.90}
```
