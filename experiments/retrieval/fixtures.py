"""Generate legal synthetic engineering data, never human annotation attestations."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from claim_trellis.document_blocks import PARSER_VERSION, text_blocks

from .dataset import SLICES, Manifest, Query, Source, frozen_passages, sha

CASES = [
    (
        "In adults, intervention A reduced systolic blood pressure.",
        "In children, intervention A reduced systolic blood pressure.",
    ),
    (
        "Intervention B reduced all-cause mortality.",
        "Intervention B reduced hospital admission but did not reduce mortality.",
    ),
    ("Treatment C decreased inflammation.", "Treatment C increased inflammation."),
    ("The accuracy of model D was 92 percent.", "The accuracy of model D was 29 percent."),
    (
        "Exposure E was associated with sleep duration.",
        "Exposure E caused an increase in sleep duration.",
    ),
    (
        "Intervention F improved mobility at six months.",
        "Intervention F improved mobility only at one week.",
    ),
    (
        "In study G, the intervention improved adult mobility.",
        "In study H, the same intervention improved adult mobility; study G measured sleep instead.",
    ),
]


def generate(output: Path) -> None:
    if output.exists():
        raise ValueError("Use an absent output directory; do not overwrite frozen data.")
    sources, passages, queries, qrels = [], [], [], []
    for split in ("dev", "test"):
        for i, (claim, negative) in enumerate(CASES):
            sid = f"synthetic-{split}-{i}"
            # >500-char blocks prevent v2 adjacent context collapsing every small fixture.
            context = (
                " This fictional source is a software engineering fixture, not a research paper."
                " Its observations, participants, protocol and results are invented."
                " The record includes distinct study arms and endpoints to exercise exact-span retrieval."
                " Additional methodological context here does not license generalization to another population."
                " No clinical or scientific conclusion can be drawn from these invented passages."
                " Source observations remain separated from reviewer decisions and ranking scores."
                " The text supplies only artificial context for testing deterministic data contracts."
                f" Fixture identity is {sid}."
            )
            texts = [claim + context, negative + context] + [
                f"Control paragraph {j} discusses laboratory record keeping and file naming."
                + context
                for j in range(10)
            ]
            text = "\n\n".join(texts)
            source = Source(
                source_id=sid,
                work_id=sid,
                split=split,
                text=text,
                sha256=sha(text),
                blocks=text_blocks(text),
                parser_version=PARSER_VERSION,
                license="Apache-2.0 (repository synthetic fixture)",
            )
            corpus = frozen_passages(source)
            positive = next(p.id for p in corpus if p.start == 0)
            negative_id = next(p.id for p in corpus if p.text.startswith(negative))
            sources.append(source)
            passages.extend(corpus)
            qid = f"query-{split}-{i}"
            queries.append(
                Query(
                    _id=qid,
                    source_id=sid,
                    split=split,
                    text=claim,
                    human_confirmed=False,
                    slices=[SLICES[i]],
                    hard_negatives={SLICES[i]: [negative_id]},
                )
            )
            qrels += [(qid, positive, 1), (qid, negative_id, 0)]
    output.mkdir(parents=True)
    for name, records in (
        ("sources.jsonl", sources),
        ("corpus.jsonl", passages),
        ("queries.jsonl", queries),
    ):
        (output / name).write_text(
            "".join(
                r.model_dump_json(
                    by_alias=True, exclude={"citation"} if name == "queries.jsonl" else set()
                )
                + "\n"
                for r in records
            )
        )
    (output / "qrels.tsv").write_text(
        "query-id\tcorpus-id\tscore\n" + "".join(f"{q}\t{p}\t{s}\n" for q, p, s in qrels)
    )
    manifest = Manifest(
        schema_version="claim-trellis-retrieval-v1",
        dataset_version="synthetic-hard-negatives-v1",
        annotation_status="synthetic-engineering",
        qrels_reviewers=[],
        adjudicator=None,
        retrieval_scope="within-identified-source",
        parser_version=PARSER_VERSION,
        retrieval_version="lexical-evidence-v2",
        files={
            name: hashlib.sha256((output / name).read_bytes()).hexdigest()
            for name in ("sources.jsonl", "corpus.jsonl", "queries.jsonl", "qrels.tsv")
        },
        notes="Invented engineering fixtures under the existing repository license, not human-confirmed atomic claims or a held-out scientific benchmark. No adoption decision may rely on these scores.",
    )
    (output / "manifest.json").write_text(json.dumps(manifest.model_dump(), indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    generate(parser.parse_args().output)
