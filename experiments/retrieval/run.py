"""Run explicitly, outside the product CLI: python -m experiments.retrieval.run."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import resource
import subprocess
from datetime import UTC, datetime
from operator import gt, lt
from pathlib import Path
from time import perf_counter

from .dataset import Dataset
from .evaluate import evaluate
from .retrievers import DenseRetriever, HybridRetriever, LexicalRetriever, SentenceEncoder


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-synthetic", action="store_true")
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--model", default="sentence-transformers/all-MiniLM-L6-v2")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--rrf-k", type=int, default=60)
    args = parser.parse_args()
    dataset = Dataset(args.dataset, allow_synthetic=args.allow_synthetic)
    if args.top_k < 10 or args.rrf_k < 1:
        parser.error("top-k >= 10 and rrf-k >= 1 required")
    if args.output.exists():
        parser.error("Use a new output directory; frozen reports are never overwritten.")
    started = perf_counter()
    encoder = SentenceEncoder(args.model, args.revision)
    model_seconds = perf_counter() - started
    started = perf_counter()
    dense = DenseRetriever(dataset, encoder)
    build_seconds = perf_counter() - started
    lexical = LexicalRetriever(dataset)
    hybrid = HybridRetriever(lexical, dense, k=args.rrf_k)
    results = [
        evaluate(dataset, r, split=args.split, top_k=args.top_k) for r in (lexical, dense, hybrid)
    ]
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip())
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    report = {
        "schema_version": "retrieval-run-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "dataset": dataset.manifest.model_dump(),
        "split_hash": dataset.split_hash,
        "commit_sha": sha,
        "working_tree_dirty": dirty,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "top_k": args.top_k,
        "rrf_k": args.rrf_k,
        "chunk_version": "production-v2-context-spans-target900-max1600",
        "embedding": encoder.provenance,
        "packages": {
            p: importlib.metadata.version(p)
            for p in ("sentence-transformers", "torch", "transformers", "numpy")
        },
        "resource": {
            "model_load_seconds": model_seconds,
            "index_build_seconds": build_seconds,
            "logical_index_bytes": dense.index_bytes,
            "peak_process_rss_bytes": rss if platform.system() == "Darwin" else rss * 1024,
            "index_disk_bytes": 0,
            "note": "In-memory exact flat index. RSS includes model and interpreter. No hosted embedding API. Hardware cost is unmeasured.",
        },
        "adoption": "NOT AUTHORIZED; production lexical-evidence-v2 unchanged",
        "results": results,
    }
    args.output.mkdir(parents=True)
    (args.output / "run.json").write_text(json.dumps(report, indent=2) + "\n")
    lines = [
        "# Retrieval ablation report",
        "",
        f"Dataset: `{dataset.manifest.dataset_version}` ({dataset.manifest.annotation_status}); split `{args.split}`.",
        "",
        "This is retrieval evaluation, not Jev judgment accuracy or scientific validation. Synthetic results are engineering regression only.",
        "",
        "| Baseline | Recall@1 | Recall@5 | Recall@10 | MRR@10 | nDCG@10 | p50/p95 ms |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        values = [f"{v:.4f}" for v in result["metrics"].values()]
        lines.append(
            f"| {result['baseline']} | "
            + " | ".join(values)
            + f" | {result['latency_ms']['p50']:.2f}/{result['latency_ms']['p95']:.2f} |"
        )
    lines += ["", "## Gains and regressions relative to lexical v2", ""]
    base = {r["query_id"]: r for r in results[0]["queries"]}
    for result in results[1:]:
        for direction, compare in (
            ("gains", gt),
            ("regressions", lt),
        ):
            ids = [
                r["query_id"]
                for r in result["queries"]
                if compare(r["metrics"]["MRR@10"], base[r["query_id"]]["metrics"]["MRR@10"])
            ]
            lines.append(
                f"- {result['baseline']} MRR@10 {direction}: {', '.join(ids) or 'none in this sample'}."
            )
    lines += [
        "",
        "## Hard-negative slices",
        "",
        "Missing slices are null, never counted as passing. Full per-query rankings, slice recall/MRR/nDCG and hard-negative exposure@5 are in `run.json`. A retrieved negative is not a false-support judgment.",
        "",
        "| Slice | Baseline | n | Recall@1 | Recall@5 | MRR@10 | Negative exposure@5 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        for name, part in result["slices"].items():
            m = part["metrics"]
            slice_values = (
                "null | null | null"
                if m is None
                else f"{m['Recall@1']:.4f} | {m['Recall@5']:.4f} | {m['MRR@10']:.4f}"
            )
            exposure = part["hard_negative_exposure@5"]
            lines.append(
                f"| {name} | {result['baseline']} | {part['query_count']} | {slice_values} | {'null' if exposure is None else f'{exposure:.4f}'} |"
            )
    lines += [
        "",
        "## Cost and reproducibility",
        "",
        f"Commit `{sha}`; dirty tree: `{dirty}`; split hash `{dataset.split_hash}`. Frozen file hashes and pinned model revision are in `run.json`.",
        "",
        f"Model load {model_seconds:.3f}s; index build {build_seconds:.3f}s; logical index {dense.index_bytes} bytes; peak process RSS {report['resource']['peak_process_rss_bytes']} bytes. Disk index: 0 (not persisted). External embedding API cost $0; local hardware cost unmeasured. Latency is a single serial CPU pass, not a service SLA. Truncated encode inputs (including repeated hybrid queries): {encoder.provenance['truncated_inputs']}.",
        "",
        "## Adoption gate",
        "",
        "No production adoption. Require owner-approved, independently annotated source-disjoint held-out data; review gains, regressions, hard negatives, truncation, latency and cost; then explicit owner approval and a separate retrieval-v3 adoption PR.",
        "",
    ]
    (args.output / "retrieval-ablation-report.md").write_text("\n".join(lines))
    print(f"Completed {len(results)} offline baselines; reports: {args.output}")


if __name__ == "__main__":
    main()
