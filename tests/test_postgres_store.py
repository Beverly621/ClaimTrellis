"""Real PostgreSQL contract tests. CI supplies a disposable *_test database."""

import asyncio
import os
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from test_revisions import RevisionProvider

from claim_trellis.audit import run_audit
from claim_trellis.config import Settings
from claim_trellis.migrations import migrate, migration_status
from claim_trellis.models import AuditRequest, HumanReviewRequest, RevisionRequest, RevisionStatus
from claim_trellis.postgres_store import PostgresAuditStore
from claim_trellis.provider import ProviderError
from claim_trellis.revisions import revise
from claim_trellis.storage import LifecycleConflict

USER_A = "11111111-1111-4111-8111-111111111111"
USER_B = "22222222-2222-4222-8222-222222222222"


@pytest.fixture(scope="session")
def pg_url() -> str:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run real PostgreSQL contract tests.")
    if conninfo_to_dict(url).get("dbname") != "claim_trellis_test":
        pytest.fail("PostgreSQL tests require a database named claim_trellis_test.")
    with psycopg.connect(make_conninfo(url, sslmode="disable"), autocommit=True) as conn:
        for role in ("anon", "authenticated"):
            if conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone() is None:
                conn.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(role)))
    assert asyncio.run(migrate(url, sslmode="disable")) in (
        ["0001_persistence.sql", "0002_provider_usage.sql", "0003_user_profiles.sql"],
        ["0002_provider_usage.sql", "0003_user_profiles.sql"],
        ["0003_user_profiles.sql"],
        [],
    )
    assert asyncio.run(migrate(url, sslmode="disable")) == []
    assert asyncio.run(migration_status(url, sslmode="disable")) == [
        ("0001_persistence.sql", True),
        ("0002_provider_usage.sql", True),
        ("0003_user_profiles.sql", True),
    ]
    return url


async def opened(url: str) -> PostgresAuditStore:
    store = PostgresAuditStore(url, sslmode="disable")
    await store.open()
    return store


async def seed(store: PostgresAuditStore, owner: str):
    provider = RevisionProvider()
    settings = Settings(jev_api_key=None)
    audit = await run_audit(
        AuditRequest(
            claim="The method improved retrieval accuracy.",
            source_text="The method improved retrieval accuracy on the secondary task.",
            source={"access_tier": "excerpt"},
        ),
        settings,
        judgment_provider=provider,
    )
    return await store.save(owner, audit), provider, settings


def ref(audit):
    return {
        "proposal_id": audit.current_proposal_id,
        "proposal_version": audit.current_proposal_version,
        "expected_state_revision": audit.state_revision,
    }


def request(audit, key=None):
    return RevisionRequest(
        **ref(audit),
        idempotency_key=key or str(uuid4()),
        reviewer="researcher",
        feedback="Check the secondary-task boundary.",
    )


@pytest.mark.asyncio
async def test_persistence_isolation_and_ordering_across_store_instances(pg_url) -> None:
    first, second = await opened(pg_url), await opened(pg_url)
    try:
        audit, _, _ = await seed(first, USER_A)
        other, _, _ = await seed(second, USER_B)
        assert (await second.get(USER_A, audit.audit_id)).claim == audit.claim
        assert await second.get(USER_B, audit.audit_id) is None
        assert audit.audit_id in [item.audit_id for item in await second.list_audits(USER_A)]
        assert audit.audit_id not in [item.audit_id for item in await second.list_audits(USER_B)]
        assert other.audit_id in [item.audit_id for item in await first.list_audits(USER_B)]
        assert other.audit_id not in [item.audit_id for item in await first.list_audits(USER_A)]
        assert "source_text" not in audit.model_dump_json()
        for operation in (second.proposals, second.revisions, second.events):
            with pytest.raises(KeyError):
                await operation(USER_B, audit.audit_id)
        events = await second.events(USER_A, audit.audit_id)
        assert [event.event_type for event in events] == [
            "audit.created",
            "source.loaded",
            "checks.completed",
            "proposal.created",
        ]
        async with first.pool.connection() as conn:
            result = await conn.execute(
                "SELECT event_seq FROM audit_events WHERE audit_id=%s ORDER BY event_seq",
                (audit.audit_id,),
            )
            seq = [row["event_seq"] for row in await result.fetchall()]
            assert seq == sorted(seq) and len(seq) == len(events)
    finally:
        await first.close()
        await second.close()


@pytest.mark.asyncio
async def test_concurrent_reviews_use_row_lock_and_stale_cas(pg_url) -> None:
    first, second = await opened(pg_url), await opened(pg_url)
    try:
        audit, _, _ = await seed(first, USER_A)

        async def review(store, decision):
            try:
                return await store.review(
                    USER_A,
                    audit.audit_id,
                    HumanReviewRequest(
                        **ref(audit), decision=decision, notes="Checked.", reviewer="r"
                    ),
                )
            except LifecycleConflict:
                return "conflict"

        results = await asyncio.gather(review(first, "accept"), review(second, "reject"))
        assert sum(result == "conflict" for result in results) == 1
        assert (
            len(
                [
                    event
                    for event in await first.events(USER_A, audit.audit_id)
                    if event.event_type.startswith("review.")
                ]
            )
            == 1
        )
    finally:
        await first.close()
        await second.close()


@pytest.mark.asyncio
async def test_active_revision_constraint_duplicate_key_and_provider_outside_transaction(
    pg_url,
) -> None:
    first, second = await opened(pg_url), await opened(pg_url)
    try:
        audit, _, settings = await seed(first, USER_A)
        entered, release = asyncio.Event(), asyncio.Event()

        class SlowProvider(RevisionProvider):
            async def evaluate(self, *args, **kwargs):
                if kwargs.get("revision_context"):
                    entered.set()
                    await release.wait()
                return await super().evaluate(*args, **kwargs)

        provider = SlowProvider()
        item = request(audit)
        task = asyncio.create_task(
            revise(first, audit.audit_id, item, settings, provider, owner_user_id=USER_A)
        )
        await asyncio.wait_for(entered.wait(), 5)
        # An independent instance can read committed events during the provider call.
        events = await asyncio.wait_for(second.events(USER_A, audit.audit_id), 5)
        assert events[-1].event_type == "revision.started"
        duplicate = await second.request_revision(USER_A, audit.audit_id, item)
        assert duplicate[1] is False
        assert duplicate[0].status == RevisionStatus.RUNNING
        with pytest.raises(LifecycleConflict):
            await second.request_revision(USER_A, audit.audit_id, request(audit))
        with pytest.raises(LifecycleConflict):
            await second.request_revision(
                USER_A,
                audit.audit_id,
                item.model_copy(update={"feedback": "Different guidance."}),
            )
        release.set()
        assert (await task).status == RevisionStatus.COMPLETED
        assert len(provider.calls) == 1
        assert len(await second.proposals(USER_A, audit.audit_id)) == 2
        assert (await second.request_revision(USER_A, audit.audit_id, item))[
            0
        ].status == RevisionStatus.COMPLETED
        with pytest.raises(LifecycleConflict):
            await second.review(
                USER_A,
                audit.audit_id,
                HumanReviewRequest(**ref(audit), decision="accept", notes="Stale.", reviewer="r"),
            )
    finally:
        await first.close()
        await second.close()


@pytest.mark.asyncio
async def test_expired_revision_fails_without_losing_parent_or_feedback(pg_url) -> None:
    store = await opened(pg_url)
    try:
        audit, _, _ = await seed(store, USER_A)
        run, created = await store.request_revision(USER_A, audit.audit_id, request(audit))
        assert created is True
        await store.start_revision(USER_A, run)
        store.REVISION_LEASE_SECONDS = -1
        failed = await store.get(USER_A, audit.audit_id)
        assert failed.review_status == RevisionStatus.FAILED
        assert (await store.revisions(USER_A, audit.audit_id))[
            0
        ].request.feedback == run.request.feedback
        assert (await store.revisions(USER_A, audit.audit_id))[0].error_code == "interrupted"
        assert len(await store.proposals(USER_A, audit.audit_id)) == 1
        late = await store.finish_revision(USER_A, run, audit.judgment_result, audit.proposal)
        assert late.status == RevisionStatus.FAILED
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_defer_reject_and_provider_failure_preserve_proposal(pg_url) -> None:
    store = await opened(pg_url)
    try:
        audit, _, settings = await seed(store, USER_A)
        deferred = await store.review(
            USER_A,
            audit.audit_id,
            HumanReviewRequest(**ref(audit), decision="defer", notes="Read later.", reviewer="r"),
        )
        assert deferred.review_status == "deferred"
        rejected = await store.review(
            USER_A,
            audit.audit_id,
            HumanReviewRequest(
                **ref(deferred), decision="reject", notes="Wrong scope.", reviewer="r"
            ),
        )
        assert rejected.review_status == "rejected"
        provider = RevisionProvider(error=ProviderError("unavailable"))
        failed = await revise(
            store,
            audit.audit_id,
            request(rejected),
            settings,
            provider,
            owner_user_id=USER_A,
        )
        assert failed.status == RevisionStatus.FAILED
        assert failed.request.feedback == "Check the secondary-task boundary."
        unchanged = await store.get(USER_A, audit.audit_id)
        assert unchanged.current_proposal_id == audit.current_proposal_id
        assert len(await store.proposals(USER_A, audit.audit_id)) == 1
        assert (await store.proposals(USER_A, audit.audit_id))[0].review_status == "revision_failed"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_sql_privileges_and_rls_defense_in_depth(pg_url) -> None:
    store = await opened(pg_url)
    try:
        async with store.pool.connection() as conn:
            result = await conn.execute(
                "SELECT relname,relrowsecurity FROM pg_class WHERE relname IN "
                "('audits','audit_events','proposal_versions','revision_runs')"
            )
            rows = await result.fetchall()
            assert len(rows) == 4 and all(row["relrowsecurity"] for row in rows)
            for role in ("anon", "authenticated"):
                for table in ("audits", "audit_events", "proposal_versions", "revision_runs"):
                    result = await conn.execute(
                        "SELECT has_table_privilege(%s,%s,'SELECT')", (role, table)
                    )
                    assert (await result.fetchone())["has_table_privilege"] is False
    finally:
        await store.close()
