from __future__ import annotations

import hashlib
import json

from claim_trellis.models import (
    ClaimAudit,
    EvidencePassage,
    EvidenceSet,
    RetrievedCandidate,
    RevisionRequest,
)

MAX_EVIDENCE_CHARS = 8000


def make_evidence_set(passages: list[EvidencePassage]) -> EvidenceSet:
    if not 1 <= len(passages) <= 3 or len({p.passage_id for p in passages}) != len(passages):
        raise ValueError("Select one to three distinct source passages.")
    passages = sorted(passages, key=lambda p: (p.start_char, p.passage_id))
    if sum(len(p.text) for p in passages) > MAX_EVIDENCE_CHARS:
        raise ValueError("Selected evidence exceeds the 8000-character budget.")
    payload = [
        {
            "passage_id": p.passage_id,
            "sha256": p.sha256,
            "locator": p.locator,
            "start_char": p.start_char,
            "end_char": p.end_char,
        }
        for p in passages
    ]
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return EvidenceSet(passages=passages, sha256=digest)


def evidence_text(evidence: EvidenceSet) -> str:
    # Mark separate source spans, preventing synthetic adjacency or quote matches.
    return "\n\n[SEPARATE SOURCE PASSAGE]\n\n".join(p.text for p in evidence.passages)


def select_initial(candidates: list[RetrievedCandidate]) -> EvidenceSet | None:
    selected: list[EvidencePassage] = []
    for candidate in candidates:
        if candidate.score <= 0 or candidate.score < candidates[0].score * 0.25:
            continue
        passage = candidate.passage
        if any(
            passage.start_char < other.end_char and other.start_char < passage.end_char
            for other in selected
        ):
            continue
        if sum(len(p.text) for p in selected) + len(passage.text) > MAX_EVIDENCE_CHARS:
            continue
        selected.append(passage)
        if len(selected) == 3:
            break
    return make_evidence_set(selected) if selected else None


def revision_evidence(audit: ClaimAudit, request: RevisionRequest) -> EvidenceSet | None:
    if request.selected_passage_ids is None:
        return audit.evidence_set or (
            make_evidence_set([audit.selected_passage]) if audit.selected_passage else None
        )
    candidates = {item.passage.passage_id: item.passage for item in audit.candidates}
    if any(passage_id not in candidates for passage_id in request.selected_passage_ids):
        raise ValueError("Select evidence only from this audit's source candidates.")
    return make_evidence_set([candidates[pid] for pid in request.selected_passage_ids])
