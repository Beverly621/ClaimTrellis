import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_paper_mapping import mapping_decision, setup_mapping, source_record
from test_paper_workflow import paper_store, pg_url, workflow_backend
from test_provider import StubProvider

from claim_trellis.api import create_app
from claim_trellis.config import Settings
from claim_trellis.models import HumanReviewRequest, utc_now
from claim_trellis.paper_matrix import projection
from claim_trellis.paper_run_models import AuditItemExecute, AuditRunCreate
from claim_trellis.paper_runs import PaperRunStore
from claim_trellis.paper_store import WorkflowNotFound
from claim_trellis.provider import ProviderError
from claim_trellis.storage import AuditStore, LifecycleConflict
from claim_trellis.store import SQLiteAsyncStore

__all__ = ["paper_store", "workflow_backend", "pg_url"]


class CountingProvider(StubProvider):
    def __init__(self, failure=None, delay=0):
        self.calls, self.failure, self.delay = 0, failure, delay

    async def evaluate(self, *args, **kwargs):
        self.calls += 1
        await asyncio.sleep(self.delay)
        if self.failure:
            raise self.failure
        return await super().evaluate(*args, **kwargs)


async def seeded(paper_store, **options):
    workflow, audits, owner = paper_store
    if not isinstance(audits, AuditStore):
        owner = str(uuid4())  # independent daily usage ledger for every contract test
    settings = Settings(
        paper_daily_user_limit=20,
        paper_run_provider_limit=10,
        paper_max_concurrent_provider_calls=2,
        **options,
    )
    if isinstance(audits, AuditStore):
        audits = SQLiteAsyncStore(legacy_store=audits)
    runs = PaperRunStore(workflow, audits, settings)
    project, manuscript, candidate, refs = await setup_mapping(workflow, owner)
    await source_record(workflow, owner, project)
    await source_record(workflow, owner, project, "10.1234/cost", "Reducing the inference cost")
    links = (await workflow.suggest_mappings(owner, project, candidate.candidate_id)).links
    for link in links:
        await workflow.decide_mapping(
            owner, project, link.link_id, mapping_decision(link.source_document_id)
        )
    return runs, owner, project, links


def plan_body(links, provider=True):
    return AuditRunCreate(
        idempotency_key=str(uuid4()),
        source_link_ids=[link.link_id for link in links],
        use_judgment_provider=provider,
    )


def execute_body(item):
    return AuditItemExecute(
        idempotency_key=str(uuid4()), input_snapshot_hash=item.input_snapshot_hash
    )


@pytest.mark.asyncio
async def test_plan_only_snapshot_idempotency_and_multisource(paper_store):
    runs, owner, project, links = await seeded(paper_store)
    body = plan_body(links)
    run = await runs.plan(owner, project, body)
    assert await runs.plan(owner, project, body) == run
    assert run.quota.runnable_now == 2 and len(run.items) == 2
    assert await runs.audits.list_audits(owner) == []
    provider = CountingProvider()
    for item in run.items:
        done = await runs.execute(
            owner, project, run.run_id, item.item_id, execute_body(item), provider
        )
        audit = await runs.audits.get(owner, done.audit_id)
        assert done.status == "completed" and audit.human_review is None
        assert not audit.proposal.auto_accepted and audit.review_status == "pending_review"
        assert audit.claim == item.snapshot.confirmed_claim
        assert audit.source.content_sha256 == item.snapshot.source_document_hash
    assert provider.calls == 2
    assert (await runs.get(owner, project, run.run_id)).status == "completed"
    assert len(await runs.workflow.list_records(owner, project, "audit_link")) == 2
    second = await runs.plan(owner, project, plan_body(links))
    assert {i.audit_id for i in second.items} == {
        i.audit_id for i in (await runs.get(owner, project, run.run_id)).items
    }


@pytest.mark.asyncio
async def test_concurrent_execute_replay_and_input_conflict(paper_store):
    runs, owner, project, links = await seeded(paper_store)
    run = await runs.plan(owner, project, plan_body(links[:1]))
    item, provider = run.items[0], CountingProvider(delay=0.05)
    body = execute_body(item)
    responses = await asyncio.gather(
        *(runs.execute(owner, project, run.run_id, item.item_id, body, provider) for _ in range(3))
    )
    assert provider.calls == 1
    completed = next(r for r in responses if r.status == "completed")
    assert (
        await runs.execute(owner, project, run.run_id, item.item_id, body, provider)
    ).audit_id == completed.audit_id
    with pytest.raises(LifecycleConflict):
        await runs.execute(
            owner,
            project,
            run.run_id,
            item.item_id,
            body.model_copy(update={"input_snapshot_hash": "0" * 64}),
            provider,
        )
    with pytest.raises(WorkflowNotFound):
        await runs.get("foreign-owner", project, run.run_id)
    with pytest.raises(WorkflowNotFound):
        await runs.execute(owner, project, "wrong-run", item.item_id, body, provider)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "gate",
    [
        "candidate_pending",
        "candidate_rejected",
        "mapping_pending",
        "mapping_rejected",
        "source_missing",
        "identity_missing",
        "input_changed",
        "source_hash_changed",
        "reference_hash_changed",
    ],
)
async def test_gates_and_changed_snapshot_are_fail_closed(paper_store, gate):
    runs, owner, project, links = await seeded(paper_store)
    run = await runs.plan(owner, project, plan_body(links[:1]))
    link = links[0]
    async with runs.workflow.transaction() as conn:
        record_id = (
            link.candidate_id
            if gate in {"candidate_pending", "candidate_rejected", "input_changed"}
            else link.reference_id
            if gate == "reference_hash_changed"
            else run.items[0].snapshot.source_document_id
            if gate == "source_hash_changed"
            else link.link_id
        )
        rows = await conn.execute(
            "SELECT record_json FROM paper_workflow_records WHERE record_id=?", (record_id,)
        )
        from claim_trellis.paper_runs import unpack

        record = unpack(rows[0]["record_json"])
        if gate in {"candidate_pending", "candidate_rejected"}:
            record.update(
                status="pending" if gate == "candidate_pending" else "rejected",
                confirmed_claim=None,
            )
        elif gate in {"mapping_pending", "mapping_rejected"}:
            record["status"] = "pending" if gate == "mapping_pending" else "rejected"
        elif gate == "source_missing":
            record.update(status="pending", source_document_id=None)
        elif gate == "input_changed":
            record["confirmed_claim"] += " changed by human"
        elif gate == "source_hash_changed":
            record["text"] += " tampered"
        elif gate == "reference_hash_changed":
            record["raw_reference"] += " tampered"
        else:
            await conn.execute(
                "DELETE FROM paper_workflow_events WHERE project_id=? AND event_type='source_link.confirmed'",
                (project,),
            )
        await conn.execute(
            "UPDATE paper_workflow_records SET record_json=? WHERE record_id=?", (record, record_id)
        )
    provider = CountingProvider()
    with pytest.raises(LifecycleConflict):
        await runs.execute(
            owner, project, run.run_id, run.items[0].item_id, execute_body(run.items[0]), provider
        )
    with pytest.raises(LifecycleConflict):
        await runs.plan(owner, project, plan_body(links[:1]))
    assert provider.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("budget", ["unconfigured", "partial", "concurrent"])
async def test_atomic_quota_no_silent_calls(paper_store, budget):
    runs, owner, project, links = await seeded(paper_store)
    if budget == "unconfigured":
        runs.settings.paper_daily_user_limit = None
    elif budget == "partial":
        runs.settings.paper_run_provider_limit = 1
    else:
        runs.settings.paper_max_concurrent_provider_calls = 1
    run = await runs.plan(owner, project, plan_body(links))
    assert run.quota.runnable_now == (0 if budget == "unconfigured" else 1)
    provider = CountingProvider(delay=0.05)
    results = await asyncio.gather(
        *(
            runs.execute(owner, project, run.run_id, i.item_id, execute_body(i), provider)
            for i in run.items
        )
    )
    assert provider.calls == (0 if budget == "unconfigured" else 1)
    assert any(r.status == "quota_blocked" for r in results)
    assert all(r.audit_id is None for r in results if r.status == "quota_blocked")
    if budget == "concurrent":
        blocked = next(r for r in results if r.status == "quota_blocked")
        assert (
            await runs.execute(
                owner, project, run.run_id, blocked.item_id, execute_body(blocked), provider
            )
        ).status == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [ProviderError("sensitive upstream message"), TimeoutError()])
async def test_terminal_provider_error_is_completed_failclosed_audit(paper_store, failure):
    runs, owner, project, links = await seeded(paper_store)
    run = await runs.plan(owner, project, plan_body(links[:1]))
    item, provider = run.items[0], CountingProvider(failure=failure)
    done = await runs.execute(
        owner, project, run.run_id, item.item_id, execute_body(item), provider
    )
    audit = await runs.audits.get(owner, done.audit_id)
    assert done.status == "completed" and audit.service_errors
    assert "sensitive" not in str(audit.service_errors) and not audit.proposal.auto_accepted
    await runs.execute(owner, project, run.run_id, item.item_id, execute_body(item), provider)
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_atomic_save_rollback_and_checkpoint_retry_no_second_call(paper_store, monkeypatch):
    runs, owner, project, links = await seeded(paper_store)
    run = await runs.plan(owner, project, plan_body(links[:1]))
    provider, item = CountingProvider(), run.items[0]
    original = runs.workflow._insert

    async def failing_insert(*args, **kwargs):
        if args[2] == "audit_link":
            raise RuntimeError("injected persistence failure")
        return await original(*args, **kwargs)

    monkeypatch.setattr(runs.workflow, "_insert", failing_insert)
    failed = await runs.execute(
        owner, project, run.run_id, item.item_id, execute_body(item), provider
    )
    assert failed.status == "failed" and failed.retry_allowed
    from claim_trellis.paper_store import stable_id

    assert (
        await runs.audits.get(
            owner, stable_id(project, "initial-audit:" + item.claim_source_link_id)
        )
        is None
    )
    assert await runs.workflow.list_records(owner, project, "audit_link") == []
    monkeypatch.setattr(runs.workflow, "_insert", original)
    done = await runs.execute(
        owner, project, run.run_id, item.item_id, execute_body(item), provider
    )
    assert done.status == "completed" and done.attempts == 2 and provider.calls == 1


@pytest.mark.asyncio
async def test_interrupted_before_call_safe_after_call_unknown_and_fenced(paper_store):
    runs, owner, project, links = await seeded(paper_store)
    run = await runs.plan(owner, project, plan_body(links))
    for n, item in enumerate(run.items):
        claimed = await runs.claim(owner, project, run.run_id, item.item_id, execute_body(item))
        if n:
            await runs.reserve(owner, claimed, run.run_id, "stub", None)
        async with runs.workflow.transaction() as conn:
            await conn.execute(
                "UPDATE paper_audit_items SET lease_until=? WHERE item_id=?",
                ((utc_now() - timedelta(seconds=2)).isoformat(), item.item_id),
            )
    recovered = await runs.get(owner, project, run.run_id)
    assert recovered.items[0].retry_allowed and not recovered.items[1].retry_allowed
    assert recovered.items[1].error_code == "provider_outcome_unknown"
    provider = CountingProvider()
    unknown = await runs.execute(
        owner, project, run.run_id, run.items[1].item_id, execute_body(run.items[1]), provider
    )
    assert unknown.status == "failed" and provider.calls == 0


@pytest.mark.asyncio
async def test_matrix_stable_multisource_pagination_and_existing_human_review(paper_store):
    runs, owner, project, links = await seeded(paper_store)
    before = await runs.workflow.events(owner, project)
    initial = await projection(runs, owner, project, 200, 0)
    assert await projection(runs, owner, project, 200, 0) == initial
    assert await runs.workflow.events(owner, project) == before
    assert initial["counts"] == {"audit_pending": 2}
    run = await runs.plan(owner, project, plan_body(links))
    for item in run.items:
        await runs.execute(
            owner, project, run.run_id, item.item_id, execute_body(item), CountingProvider()
        )
    pending = await projection(runs, owner, project, 200, 0)
    assert pending["counts"] == {"review_pending": 2}
    assert [r["row_id"] for r in pending["rows"]] == [r["row_id"] for r in initial["rows"]]
    row = pending["rows"][0]
    assert row["raw_relation"] == "supports" and row["policy_status"] != "supports"
    assert row["evidence"] and row["human_decision"] is None
    await runs.audits.review(
        owner,
        row["audit_id"],
        HumanReviewRequest(
            decision="accept",
            notes="Read evidence",
            reviewer="Human",
            proposal_id=row["proposal_id"],
            proposal_version=row["proposal_version"],
            expected_state_revision=row["audit_state_revision"],
        ),
    )
    accepted = await projection(runs, owner, project, 1, 0)
    assert accepted["rows"][0]["workflow_state"] == "accepted"
    assert accepted["total"] == 2 and len(accepted["rows"]) == 1
    with pytest.raises(WorkflowNotFound):
        await projection(runs, "foreign-owner", project, 200, 0)


def test_paper_routes_are_additive_and_strict(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        assert client.get("/projects").status_code == 200
        assert client.get("/api/v1/projects/missing/matrix").status_code == 404
        assert (
            client.post(
                "/api/v1/projects/missing/audit-runs",
                json={
                    "idempotency_key": "run-test",
                    "source_link_ids": ["x"],
                    "owner_user_id": "forged",
                },
            ).status_code
            == 422
        )
        paths = client.get("/openapi.json").json()["paths"]
        assert not any("paper-verdict" in p for p in paths)


@pytest.mark.parametrize("path", ["", "/p/matrix", "/p/audit-runs"])
def test_unmigrated_workflow_returns_safe_503_without_breaking_p0(tmp_path, monkeypatch, path):
    from psycopg.errors import UndefinedTable

    app = create_app(Settings(data_dir=tmp_path))

    async def missing(*args, **kwargs):
        raise UndefinedTable("private SQL connection details must not reach the browser")

    monkeypatch.setattr(app.state.paper_workflow_store, "list_projects", missing)
    monkeypatch.setattr(app.state.paper_workflow_store, "_project", missing)
    with TestClient(app) as client:
        response = client.get("/api/v1/projects" + path)
        assert response.status_code == 503
        assert "migrations" in response.json()["detail"]
        assert "private SQL" not in response.text
        assert client.get("/healthz").status_code == 200
        assert client.get("/").status_code == 200


@pytest.mark.asyncio
async def test_cached_provider_result_survives_missing_full_checkpoint(paper_store, monkeypatch):
    runs, owner, project, links = await seeded(paper_store)
    run = await runs.plan(owner, project, plan_body(links[:1]))
    item, provider = run.items[0], CountingProvider()
    original = runs.checkpoint

    async def fail_checkpoint(*args):
        raise RuntimeError("crash after typed result was cached")

    monkeypatch.setattr(runs, "checkpoint", fail_checkpoint)
    failed = await runs.execute(
        owner, project, run.run_id, item.item_id, execute_body(item), provider
    )
    assert failed.status == "failed" and failed.retry_allowed
    runs.settings.paper_run_provider_limit = 1
    preflight = (await runs.get(owner, project, run.run_id)).quota
    assert preflight.provider_calls_available == 0 and preflight.runnable_now == 1
    monkeypatch.setattr(runs, "checkpoint", original)
    done = await runs.execute(
        owner, project, run.run_id, item.item_id, execute_body(item), provider
    )
    assert done.status == "completed" and provider.calls == 1


@pytest.mark.asyncio
async def test_cancellation_unknown_no_automatic_second_call(paper_store):
    runs, owner, project, links = await seeded(paper_store)
    run = await runs.plan(owner, project, plan_body(links[:1]))
    item, provider = run.items[0], CountingProvider(failure=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await runs.execute(owner, project, run.run_id, item.item_id, execute_body(item), provider)
    failed = (await runs.get(owner, project, run.run_id)).items[0]
    assert failed.status == "failed" and not failed.retry_allowed
    assert failed.error_code == "provider_outcome_unknown"
    preflight = (await runs.get(owner, project, run.run_id)).quota
    assert preflight.runnable_now == 0 and preflight.blocked == 1
    assert preflight.reason == "provider_outcome_unknown"
    await runs.execute(owner, project, run.run_id, item.item_id, execute_body(item), provider)
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_plan_rollback_canonical_input_and_safe_retry_bound(paper_store, monkeypatch):
    runs, owner, project, links = await seeded(paper_store)
    before = await runs.workflow.events(owner, project)
    with pytest.raises(WorkflowNotFound):
        await runs.plan(
            owner,
            project,
            AuditRunCreate(
                idempotency_key=str(uuid4()), source_link_ids=[links[0].link_id, "missing"]
            ),
        )
    assert await runs.list(owner, project) == []
    assert await runs.workflow.events(owner, project) == before
    body = plan_body(links[:1])
    run = await runs.plan(owner, project, body)
    with pytest.raises(LifecycleConflict):
        await runs.plan(owner, project, body.model_copy(update={"use_judgment_provider": False}))
    with pytest.raises(LifecycleConflict):
        await runs.plan(owner, project, plan_body(links[:1], False))
    item, provider = run.items[0], CountingProvider()

    async def fail_checkpoint(*args):
        raise RuntimeError("safe repeated storage failure")

    monkeypatch.setattr(runs, "checkpoint", fail_checkpoint)
    for attempt in range(3):
        failed = await runs.execute(
            owner, project, run.run_id, item.item_id, execute_body(item), provider
        )
        assert failed.attempts == attempt + 1
    final = await runs.execute(
        owner, project, run.run_id, item.item_id, execute_body(item), provider
    )
    assert final.attempts == 3 and not final.retry_allowed and provider.calls == 1
    assert (await runs.get(owner, project, run.run_id)).quota.runnable_now == 0


@pytest.mark.asyncio
async def test_running_item_is_not_advertised_as_runnable(paper_store):
    runs, owner, project, links = await seeded(paper_store)
    run = await runs.plan(owner, project, plan_body(links[:1]))
    await runs.claim(owner, project, run.run_id, run.items[0].item_id, execute_body(run.items[0]))
    preflight = (await runs.get(owner, project, run.run_id)).quota
    assert preflight.runnable_now == 0 and preflight.blocked == 1
    assert preflight.reason == "execution_in_progress"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "decision,status",
    [("reject", "rejected"), ("defer", "deferred"), ("revise", "revision_requested")],
)
async def test_matrix_tracks_ordinary_review_states_and_stale_cas(paper_store, decision, status):
    runs, owner, project, links = await seeded(paper_store)
    run = await runs.plan(owner, project, plan_body(links[:1]))
    item = run.items[0]
    done = await runs.execute(
        owner, project, run.run_id, item.item_id, execute_body(item), CountingProvider()
    )
    audit = await runs.audits.get(owner, done.audit_id)
    request = HumanReviewRequest(
        decision=decision,
        notes="Original source reviewed",
        reviewer="Human",
        proposal_id=audit.current_proposal_id,
        proposal_version=audit.current_proposal_version,
        expected_state_revision=audit.state_revision,
    )
    if decision == "revise":
        from claim_trellis.models import RevisionRequest

        revision_request = RevisionRequest(
            idempotency_key=str(uuid4()),
            proposal_id=audit.current_proposal_id,
            proposal_version=1,
            expected_state_revision=audit.state_revision,
            reviewer="Human",
            feedback="Original source reviewed",
        )
        await runs.audits.request_revision(owner, audit.audit_id, revision_request)
        with pytest.raises(LifecycleConflict):
            await runs.audits.request_revision(
                owner,
                audit.audit_id,
                revision_request.model_copy(update={"idempotency_key": str(uuid4())}),
            )
    else:
        await runs.audits.review(owner, audit.audit_id, request)
        with pytest.raises(LifecycleConflict):
            await runs.audits.review(owner, audit.audit_id, request)
    matrix = await projection(runs, owner, project, 200, 0)
    row = next(r for r in matrix["rows"] if r["audit_id"] == audit.audit_id)
    assert row["workflow_state"] == status and row["raw_relation"] == "supports"


@pytest.mark.asyncio
async def test_project_audit_can_use_ordinary_revision_without_second_initial_audit(paper_store):
    from test_revisions import RevisionProvider

    from claim_trellis.models import RevisionRequest
    from claim_trellis.revisions import revise

    runs, owner, project, links = await seeded(paper_store)
    run = await runs.plan(owner, project, plan_body(links[:1]))
    item = run.items[0]
    done = await runs.execute(
        owner, project, run.run_id, item.item_id, execute_body(item), CountingProvider()
    )
    audit = await runs.audits.get(owner, done.audit_id)
    revision = await revise(
        runs.audits,
        audit.audit_id,
        RevisionRequest(
            idempotency_key=str(uuid4()),
            proposal_id=audit.current_proposal_id,
            proposal_version=1,
            expected_state_revision=audit.state_revision,
            reviewer="Human",
            feedback="Keep the task boundary explicit",
        ),
        runs.settings,
        RevisionProvider(),
        owner_user_id=owner,
    )
    assert revision.status == "revision_completed"
    matrix = await projection(runs, owner, project, 200, 0)
    row = next(r for r in matrix["rows"] if r["audit_id"] == audit.audit_id)
    assert (
        row["proposal_version"] == 2
        and row["raw_relation"] == "partially_supports"
        and row["workflow_state"] == "review_pending"
    )
    assert len(await runs.workflow.list_records(owner, project, "audit_link")) == 1


@pytest.mark.asyncio
async def test_hosted_reservation_is_atomic_with_existing_ip_guard(paper_store):
    from claim_trellis.postgres_store import PostgresAuditStore

    if not isinstance(paper_store[1], PostgresAuditStore):
        return
    runs, owner, project, links = await seeded(paper_store)
    runs.settings.auth_mode = "supabase"
    ip = str(uuid4())
    run = await runs.plan(owner, project, plan_body(links))
    async with runs.workflow.transaction() as conn:
        for _ in range(10):
            await conn.execute(
                "INSERT INTO provider_usage(usage_id,owner_user_id,ip_hash,provider,operation,status) VALUES(?,?,?,'stub','audit','succeeded')",
                (str(uuid4()), str(uuid4()), ip),
            )
    provider = CountingProvider()
    item = run.items[0]
    blocked = await runs.execute(
        owner, project, run.run_id, item.item_id, execute_body(item), provider, ip
    )
    assert blocked.error_code == "hosted_ip_limit" and provider.calls == 0
    async with runs.workflow.transaction() as conn:
        assert (
            await conn.execute(
                "SELECT count(*) AS n FROM paper_provider_usage WHERE owner_user_id=?", (owner,)
            )
        )[0]["n"] == 0
    done = await runs.execute(
        owner, project, run.run_id, item.item_id, execute_body(item), provider, str(uuid4())
    )
    assert done.status == "completed" and provider.calls == 1
    async with runs.workflow.transaction() as conn:
        paper = (
            await conn.execute(
                "SELECT usage_id,status FROM paper_provider_usage WHERE owner_user_id=?", (owner,)
            )
        )[0]
        hosted = (
            await conn.execute(
                "SELECT usage_id,status FROM provider_usage WHERE owner_user_id=?", (owner,)
            )
        )[0]
        assert paper == hosted and paper["status"] == "succeeded"


def test_http_project_loop_three_claims_four_sources_and_unmapped(tmp_path):
    from test_paper_mapping import PAPER

    text = (
        PAPER.replace(
            "\n\nReferences",
            "\nModel A reduces cost [12].\nModel A improves reliability [17, 99].\n\nReferences",
        )
        + "\n[99] Synthetic Missing Source. 2025."
    )
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app) as client:
        project = client.post(
            "/api/v1/projects",
            json={"name": "Synthetic component acceptance", "idempotency_key": "component-project"},
        ).json()["project_id"]
        base = f"/api/v1/projects/{project}"
        manuscript = client.post(
            base + "/manuscripts",
            json={
                "filename": "synthetic.txt",
                "text": text,
                "idempotency_key": "component-manuscript",
            },
        ).json()
        path = base + "/manuscripts/" + manuscript["manuscript_id"]
        candidates = client.post(path + "/extract-candidates").json()
        assert len(candidates) == 3
        client.post(path + "/parse-references")
        for title, doi in [
            ("Advances in inference accuracy", "10.1234/accuracy"),
            ("Reducing the inference cost", "10.1234/cost"),
        ]:
            response = client.post(
                base + "/sources",
                files={
                    "document": (
                        "synthetic.txt",
                        b"Model A improves accuracy and reduces cost. Model A improves reliability.",
                        "text/plain",
                    )
                },
                data={
                    "idempotency_key": str(uuid4()),
                    "metadata": __import__("json").dumps({"title": title, "doi": doi}),
                },
            )
            assert response.status_code == 201
        links = []
        for c in candidates:
            response = client.post(
                base + f"/candidates/{c['candidate_id']}/decisions",
                json={
                    "idempotency_key": str(uuid4()),
                    "decision": "confirm",
                    "expected_state_revision": 0,
                    "reviewer": "Synthetic tester",
                    "notes": "Synthetic fixture only",
                    "rubric": {"atomic": True, "faithful": True, "necessary_context": True},
                },
            )
            assert response.status_code == 200
            suggestions = client.post(
                base + f"/candidates/{c['candidate_id']}/suggest-mappings"
            ).json()
            for link in suggestions["links"]:
                if link["source_document_id"]:
                    assert (
                        client.post(
                            base + f"/source-links/{link['link_id']}/decisions",
                            json=mapping_decision(link["source_document_id"]).model_dump(
                                mode="json"
                            ),
                        ).status_code
                        == 200
                    )
                    links.append(link["link_id"])
        matrix = client.get(base + "/matrix").json()
        assert matrix["total"] == 5 and matrix["counts"] == {
            "audit_pending": 4,
            "source_unmapped": 1,
        }
        run = client.post(
            base + "/audit-runs",
            json={
                "idempotency_key": "component-run",
                "source_link_ids": links,
                "use_judgment_provider": False,
            },
        ).json()
        assert run["quota"]["runnable_now"] == 4
        for item in run["items"]:
            response = client.post(
                base + f"/audit-runs/{run['run_id']}/items/{item['item_id']}/execute",
                json={
                    "idempotency_key": "execute-component",
                    "input_snapshot_hash": item["input_snapshot_hash"],
                },
            )
            assert response.status_code == 200 and response.json()["status"] == "completed"
        assert client.get(base + f"/audit-runs/{run['run_id']}").json()["status"] == "completed"
        assert len(client.get(base + "/audit-runs").json()) == 1
        matrix = client.get(base + "/matrix").json()
        assert matrix["counts"] == {"review_pending": 4, "source_unmapped": 1}
        for row in matrix["rows"]:
            if row["audit_id"]:
                assert client.get(f"/api/v1/audits/{row['audit_id']}/events").status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "label",
    [
        "supports",
        "partially_supports",
        "contradicts",
        "not_addressed",
        "insufficient_context",
        "source_unavailable",
    ],
)
async def test_all_six_relations_complete_without_semantic_retry_or_auto_accept(paper_store, label):
    from test_provider import choice

    runs, owner, project, links = await seeded(paper_store, auto_accept_enabled=True)

    class SemanticProvider(CountingProvider):
        async def evaluate(self, *args, **kwargs):
            result = await super().evaluate(*args, **kwargs)
            result.relation = choice(label)
            return result

    provider = SemanticProvider()
    run = await runs.plan(owner, project, plan_body(links[:1]))
    item = run.items[0]
    done = await runs.execute(
        owner, project, run.run_id, item.item_id, execute_body(item), provider
    )
    audit = await runs.audits.get(owner, done.audit_id)
    assert done.status == "completed" and not done.retry_allowed
    assert audit.judgment_result.relation.choice == label and audit.human_review is None
    assert not audit.proposal.auto_accepted and audit.review_status == "pending_review"
    await runs.execute(owner, project, run.run_id, item.item_id, execute_body(item), provider)
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_expired_provider_lease_does_not_strand_global_concurrency(paper_store):
    runs, owner, project, links = await seeded(paper_store)
    runs.settings.paper_max_concurrent_provider_calls = 1
    run = await runs.plan(owner, project, plan_body(links))
    first, second = run.items
    claimed = await runs.claim(owner, project, run.run_id, first.item_id, execute_body(first))
    await runs.reserve(owner, claimed, run.run_id, "stub", None)
    async with runs.workflow.transaction() as conn:
        await conn.execute(
            "UPDATE paper_audit_items SET lease_until=? WHERE item_id=?",
            ((utc_now() - timedelta(seconds=2)).isoformat(), first.item_id),
        )
    provider = CountingProvider()
    done = await runs.execute(
        owner, project, run.run_id, second.item_id, execute_body(second), provider
    )
    assert done.status == "completed" and provider.calls == 1
    recovered = (await runs.get(owner, project, run.run_id)).items[0]
    assert recovered.error_code == "provider_outcome_unknown" and not recovered.retry_allowed
