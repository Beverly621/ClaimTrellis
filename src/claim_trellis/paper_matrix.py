"""Read-only projection; raw relation, policy proposal and human judgment stay separate."""

from collections import Counter
from typing import Annotated, Any

from fastapi import APIRouter, Query

from claim_trellis.models import ClaimAudit
from claim_trellis.paper_api import Principal, checked
from claim_trellis.paper_run_api import Store
from claim_trellis.paper_runs import PaperRunStore, unpack
from claim_trellis.paper_store import _Connection

router = APIRouter(prefix="/api/v1/projects", tags=["Paper Matrix"])


def workflow_state(
    claim: dict[str, Any],
    link: dict[str, Any],
    item: dict[str, Any] | None,
    audit: ClaimAudit | None,
) -> str:
    if claim.get("status") != "confirmed":
        return "claim_rejected" if claim.get("status") == "rejected" else "claim_pending"
    if link.get("status") == "rejected":
        return "mapping_rejected"
    if not link.get("source_document_id"):
        return "source_unmapped"
    if link.get("status") != "confirmed":
        return "mapping_pending"
    if audit is None:
        state = (item or {}).get("status", "pending")
        return {
            "running": "audit_running",
            "failed": "audit_failed",
            "quota_blocked": "quota_blocked",
        }.get(state, "audit_pending")
    return {
        "pending_review": "review_pending",
        "accepted": "accepted",
        "rejected": "rejected",
        "deferred": "deferred",
        "revision_requested": "revision_requested",
        "revision_running": "revision_requested",
        "revision_failed": "revision_requested",
    }.get(audit.review_status.value, "review_pending")


async def projection(
    store: PaperRunStore, owner: str, project: str, limit: int, offset: int
) -> dict[str, Any]:
    async with store.workflow.transaction() as conn:
        await store.workflow._project(conn, owner, project)
        records = await conn.execute(
            "SELECT kind,record_json FROM paper_workflow_records WHERE project_id=? AND owner_user_id=? AND kind IN ('candidate','reference','source_link','audit_link') ORDER BY record_id",
            (project, owner),
        )
        grouped: dict[str, list[dict[str, Any]]] = {
            k: [] for k in ["candidate", "reference", "source_link", "audit_link"]
        }
        for record in records:
            grouped[record["kind"]].append(unpack(record["record_json"]))
        claims = {r["candidate_id"]: r for r in grouped["candidate"]}
        refs = {r["reference_id"]: r for r in grouped["reference"]}
        associations = {r["claim_source_link_id"]: r["audit_id"] for r in grouped["audit_link"]}
        items = await conn.execute(
            "SELECT record_json FROM paper_audit_items WHERE project_id=? AND owner_user_id=? ORDER BY item_id",
            (project, owner),
        )
        by_link = {r["claim_source_link_id"]: r for r in (unpack(i["record_json"]) for i in items)}
        audits = await linked_audits(conn, owner, project)

        def json_field(name: str) -> str:
            return (
                f"record_json->>'{name}'"
                if conn.postgres
                else f"json_extract(record_json,'$.{name}')"
            )

        # Read source identity metadata only, not every source's full normalized text.
        source_rows = await conn.execute(
            f"SELECT record_id,{json_field('filename')} AS filename,{json_field('metadata.title' if not conn.postgres else 'metadata')} AS metadata,{json_field('document_hash')} AS document_hash,{json_field('parser_version')} AS parser_version FROM paper_workflow_records WHERE project_id=? AND owner_user_id=? AND kind='source_document'",
            (project, owner),
        )
        sources = {}
        for source in source_rows:
            title = unpack(source["metadata"]).get("title") if conn.postgres else source["metadata"]
            sources[source["record_id"]] = {
                "source_document_id": source["record_id"],
                "filename": source["filename"],
                "title": title,
                "document_hash": source["document_hash"],
                "parser_version": source["parser_version"],
            }
        rows = []
        for link in grouped["source_link"]:
            claim, ref = claims.get(link["candidate_id"], {}), refs.get(link["reference_id"], {})
            audit = audits.get(associations.get(link["link_id"], ""))
            item = by_link.get(link["link_id"])
            rows.append(
                {
                    "row_id": link["link_id"],
                    "candidate_id": link["candidate_id"],
                    "manuscript_id": claim.get("manuscript_id"),
                    "original_span": claim.get("original_span"),
                    "confirmed_claim": claim.get("confirmed_claim"),
                    "candidate_state_revision": claim.get("state_revision"),
                    "reference_id": link["reference_id"],
                    "citation": ref.get("raw_reference"),
                    "source_document_id": link.get("source_document_id"),
                    "source": sources.get(link.get("source_document_id")),
                    "mapping_status": link["status"],
                    "mapping_state_revision": link["state_revision"],
                    "workflow_state": workflow_state(claim, link, item, audit),
                    "run_id": item.get("run_id") if item else None,
                    "item_id": item.get("item_id") if item else None,
                    "input_snapshot_hash": item.get("input_snapshot_hash") if item else None,
                    "error_code": item.get("error_code") if item else None,
                    "retry_allowed": item.get("retry_allowed") if item else None,
                    "audit_id": audit.audit_id if audit else None,
                    "raw_relation": audit.judgment_result.relation.choice
                    if audit and audit.judgment_result
                    else None,
                    "policy_status": audit.proposal.status.value if audit else None,
                    "policy_reasons": audit.proposal.reasons if audit else [],
                    "service_errors": audit.service_errors if audit else [],
                    "review_status": audit.review_status.value if audit else None,
                    "human_decision": audit.human_review.decision.value
                    if audit and audit.human_review
                    else None,
                    "proposal_id": audit.current_proposal_id if audit else None,
                    "proposal_version": audit.current_proposal_version if audit else None,
                    "audit_state_revision": audit.state_revision if audit else None,
                    "evidence": [
                        {
                            "passage_id": p.passage_id,
                            "text": p.text,
                            "locator": p.locator,
                            "sha256": p.sha256,
                        }
                        for p in (audit.evidence_set.passages if audit.evidence_set else [])
                    ]
                    if audit
                    else [],
                }
            )
        return {
            "project_id": project,
            "rows": rows[offset : offset + limit],
            "total": len(rows),
            "offset": offset,
            "limit": limit,
            "counts": dict(sorted(Counter(r["workflow_state"] for r in rows).items())),
        }


async def linked_audits(conn: _Connection, owner: str, project: str) -> dict[str, ClaimAudit]:
    # Scoped joins avoid N+1 connections and never load other owners' audits.
    owner_clause = " AND a.owner_user_id=r.owner_user_id" if conn.postgres else ""
    audit_id_expr = (
        "r.record_json->>'audit_id'"
        if conn.postgres
        else "json_extract(r.record_json,'$.audit_id')"
    )
    rows = await conn.execute(
        f"SELECT a.record_json FROM paper_workflow_records r JOIN audits a ON a.audit_id={audit_id_expr}{owner_clause} WHERE r.project_id=? AND r.owner_user_id=? AND r.kind='audit_link'",
        (project, owner),
    )
    return {
        a.audit_id: a
        for a in (ClaimAudit.model_validate(unpack(row["record_json"])) for row in rows)
    }


@router.get("/{project_id}/matrix")
async def matrix(
    project_id: str,
    identity: Principal,
    store: Store,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    return await checked(projection(store, identity.user_id, project_id, limit, offset))
