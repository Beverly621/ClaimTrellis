import asyncio
from uuid import uuid4

import pytest
from test_audit_fidelity import source_text
from test_postgres_store import USER_A, USER_B, opened, pg_url, ref
from test_revisions import RevisionProvider

from claim_trellis.audit import run_audit
from claim_trellis.config import Settings
from claim_trellis.models import AuditRequest, RevisionRequest, RevisionStatus
from claim_trellis.provider import ProviderError
from claim_trellis.revisions import revise
from claim_trellis.storage import LifecycleConflict

# Explicitly register the existing disposable-database fixture.
__all__ = ["pg_url"]


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_postgres_evidence_snapshots_and_owner_isolation(pg_url, fail):
    store = await opened(pg_url)
    try:
        provider = RevisionProvider(error=ProviderError("test-only") if fail else None)
        settings = Settings(jev_api_key=None)
        audit = await store.save(
            USER_A,
            await run_audit(
                AuditRequest(
                    claim="The intervention decreased the endpoint.", source_text=source_text()
                ),
                settings,
                judgment_provider=provider,
            ),
        )
        old = (await store.proposals(USER_A, audit.audit_id))[0]
        selected = [audit.candidates[-1].passage.passage_id]
        request = RevisionRequest(
            **ref(audit),
            reviewer="human",
            feedback="Verify the other cohort.",
            idempotency_key=str(uuid4()),
            selected_passage_ids=selected,
        )
        with pytest.raises(KeyError):
            await store.request_revision(USER_B, audit.audit_id, request)
        assert await store.get(USER_B, audit.audit_id) is None
        invalid = request.model_copy(update={"selected_passage_ids": ["foreign-id"]})
        with pytest.raises(LifecycleConflict):
            await store.request_revision(USER_A, audit.audit_id, invalid)
        assert (await store.get(USER_A, audit.audit_id)).state_revision == audit.state_revision
        result = await revise(
            store, audit.audit_id, request, settings, provider, owner_user_id=USER_A
        )
        assert result.status == (RevisionStatus.FAILED if fail else RevisionStatus.COMPLETED)
        current = await store.get(USER_A, audit.audit_id)
        assert (await store.proposals(USER_A, audit.audit_id))[0].evidence_set == old.evidence_set
        replay = await revise(
            store, audit.audit_id, request, settings, provider, owner_user_id=USER_A
        )
        assert replay == result
        assert len(provider.calls) == 2
        if fail:
            assert current.evidence_set == audit.evidence_set
            assert current.current_proposal_version == 1
        else:
            assert current.current_proposal_version == 2
            assert [p.passage_id for p in current.evidence_set.passages] == selected
            assert (await store.proposals(USER_A, audit.audit_id))[
                -1
            ].deterministic_checks == current.deterministic_checks
            events = await store.events(USER_A, audit.audit_id)
            assert any(
                e.event_type == "evidence.selection.changed"
                and e.payload["new_hash"] == current.evidence_set.sha256
                for e in events
            )
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_postgres_concurrent_evidence_requests_only_one_wins(pg_url):
    store = await opened(pg_url)
    try:
        settings = Settings(jev_api_key=None)
        audit = await store.save(
            USER_A,
            await run_audit(
                AuditRequest(
                    claim="The intervention decreased the endpoint.",
                    source_text=source_text(),
                    use_judgment_provider=False,
                ),
                settings,
            ),
        )

        def request(index):
            return RevisionRequest(
                **ref(audit),
                reviewer="human",
                feedback="Select the other cohort.",
                idempotency_key=str(uuid4()),
                selected_passage_ids=[audit.candidates[index].passage.passage_id],
            )

        results = await asyncio.gather(
            store.request_revision(USER_A, audit.audit_id, request(-1)),
            store.request_revision(USER_A, audit.audit_id, request(-2)),
            return_exceptions=True,
        )
        assert sum(isinstance(item, LifecycleConflict) for item in results) == 1
        assert len(await store.revisions(USER_A, audit.audit_id)) == 1
    finally:
        await store.close()
