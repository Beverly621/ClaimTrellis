from __future__ import annotations

import asyncio

from claim_trellis.config import Settings
from claim_trellis.hosted_usage import HostedUsageLimit, MeteredProvider, PostgresUsageGuard
from claim_trellis.models import RevisionContext, RevisionRequest, RevisionRun
from claim_trellis.policy import propose_disposition
from claim_trellis.provider import JudgmentProvider, ProviderError
from claim_trellis.providers import TypeSafeJevProvider
from claim_trellis.storage import AuditStore
from claim_trellis.store import LOCAL_USER_ID, AuditStoreProtocol, SQLiteAsyncStore


async def revise(
    store: AuditStoreProtocol | AuditStore,
    audit_id: str,
    request: RevisionRequest,
    settings: Settings,
    provider: JudgmentProvider | None = None,
    *,
    owner_user_id: str = LOCAL_USER_ID,
    usage_guard: PostgresUsageGuard | None = None,
    ip_hash: str | None = None,
) -> RevisionRun:
    lifecycle_store = (
        SQLiteAsyncStore(legacy_store=store) if isinstance(store, AuditStore) else store
    )
    run, is_new = await lifecycle_store.request_revision(owner_user_id, audit_id, request)
    if not is_new:
        return run
    await lifecycle_store.start_revision(owner_user_id, run)
    try:
        audit = await lifecycle_store.get(owner_user_id, audit_id)
        if audit is None or audit.selected_passage is None:
            return await lifecycle_store.fail_revision(
                owner_user_id,
                run,
                "evidence_unavailable",
                "No evidence passage is available for revision.",
            )
        if (
            provider is None
            and settings.judgment_provider == "typesafe_jev"
            and settings.jev_api_key
        ):
            provider = TypeSafeJevProvider(
                api_key=settings.jev_api_key,
                endpoint=settings.jev_endpoint,
                model=settings.jev_model,
                timeout_seconds=settings.jev_timeout_seconds,
                max_retries=settings.jev_max_retries,
            )
        if provider is None:
            return await lifecycle_store.fail_revision(
                owner_user_id,
                run,
                "provider_unavailable",
                "Configure the judgment provider before retrying.",
            )
        if usage_guard is not None:
            if ip_hash is None:
                raise ValueError("Hosted revision requires a requester IP hash.")
            provider = MeteredProvider(
                provider,
                usage_guard,
                owner_user_id,
                ip_hash,
                "revision",
                audit_id=audit_id,
                usage_id=run.revision_id,
            )
        context = RevisionContext(
            previous_proposal=(await lifecycle_store.proposals(owner_user_id, audit_id))[-1],
            deterministic_checks=audit.deterministic_checks,
            source_completeness=audit.source.access_tier,
            human_feedback=request.feedback,
            revision_number=audit.current_proposal_version + 1,
        )
        async with asyncio.timeout(90):
            judgment = await provider.evaluate(
                audit.claim, audit.selected_passage.text, audit.citation, revision_context=context
            )
        policy = propose_disposition(
            audit.deterministic_checks,
            judgment,
            source_access_tier=audit.source.access_tier,
            relation_confidence_threshold=settings.relation_confidence_threshold,
            alignment_confidence_threshold=settings.alignment_confidence_threshold,
        )
        return await lifecycle_store.finish_revision(owner_user_id, run, judgment, policy)
    except asyncio.CancelledError:
        await asyncio.shield(
            lifecycle_store.fail_revision(
                owner_user_id,
                run,
                "interrupted",
                "Evaluation was interrupted. Retry with the preserved feedback.",
            )
        )
        raise
    except HostedUsageLimit:
        await lifecycle_store.fail_revision(
            owner_user_id,
            run,
            "hosted_provider_limit",
            "Hosted provider usage limit reached. Try again later.",
        )
        raise
    except TimeoutError:
        return await lifecycle_store.fail_revision(
            owner_user_id,
            run,
            "timeout",
            "Provider timed out. Your original proposal and feedback are preserved.",
        )
    except ProviderError:
        return await lifecycle_store.fail_revision(
            owner_user_id,
            run,
            "provider_error",
            "Provider evaluation failed. Retry after checking provider availability.",
        )
    except (ValueError, TypeError, KeyError, AttributeError):
        return await lifecycle_store.fail_revision(
            owner_user_id,
            run,
            "invalid_response",
            "Provider returned an invalid structured judgment.",
        )
    except Exception:
        # Do not leak provider response bodies, keys or source content through errors.
        return await lifecycle_store.fail_revision(
            owner_user_id,
            run,
            "evaluation_error",
            "Evaluation failed. Your feedback is preserved for retry.",
        )
