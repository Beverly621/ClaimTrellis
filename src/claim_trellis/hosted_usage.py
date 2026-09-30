"""Database-atomic limits for calls paid for by the hosted Jev key."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import os
from typing import Any, Literal
from uuid import uuid4

from fastapi import Request
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from claim_trellis.models import JudgmentResult, RevisionContext
from claim_trellis.provider import JudgmentProvider, ProviderError

Operation = Literal["audit", "revision"]
Scope = Literal["user", "ip", "audit_revision"]


class HostedUsageLimit(Exception):
    def __init__(self, scope: Scope) -> None:
        self.scope = scope
        super().__init__("Hosted provider usage limit reached. Try again later.")


class HostedProviderUnavailable(Exception):
    """A required hosted-only guard input is missing or untrusted."""


def requester_ip_hash(request: Request, secret: str) -> str:
    """Trust only Vercel's overwritten forwarding header, never a client-supplied chain."""

    if not secret:
        raise HostedProviderUnavailable("Hosted provider is unavailable.")
    if os.getenv("VERCEL") == "1":
        raw = request.headers.get("x-forwarded-for", "")
        try:
            canonical = ipaddress.ip_address(raw).packed
        except ValueError as exc:
            raise HostedProviderUnavailable("Hosted provider is unavailable.") from exc
    else:
        # Local development is not a trusted Vercel IP boundary.
        canonical = b"local-workspace"
    return hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()


class PostgresUsageGuard:
    """Reserve under transaction-scoped advisory locks; commit before calling Jev."""

    USER_LIMIT = 7
    IP_LIMIT = 10
    AUDIT_REVISION_LIMIT = 5

    def __init__(self, pool: AsyncConnectionPool[AsyncConnection[dict[str, Any]]]) -> None:
        self.pool = pool

    async def reserve(
        self,
        owner_user_id: str,
        ip_hash: str,
        provider: str,
        operation: Operation,
        *,
        audit_id: str | None = None,
        usage_id: str | None = None,
    ) -> str:
        identifier = usage_id or str(uuid4())
        async with self.pool.connection() as conn:
            # Every caller takes these locks in the same order, across all app instances.
            for key in (
                f"claim-trellis-usage:user:{owner_user_id}",
                f"claim-trellis-usage:ip:{ip_hash}",
                *([f"claim-trellis-usage:audit:{audit_id}"] if audit_id else []),
            ):
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s::text, 0))", (key,)
                )
            existing = await conn.execute(
                "SELECT 1 FROM provider_usage WHERE usage_id=%s", (identifier,)
            )
            if await existing.fetchone() is not None:
                raise HostedProviderUnavailable("Hosted provider request already reserved.")
            for column, value, limit in (
                ("owner_user_id", owner_user_id, self.USER_LIMIT),
                ("ip_hash", ip_hash, self.IP_LIMIT),
            ):
                result = await conn.execute(
                    f"SELECT count(*) AS n FROM provider_usage WHERE {column}=%s "
                    "AND created_at >= now() - interval '24 hours'",
                    (value,),
                )
                row = await result.fetchone()
                if row is not None and row["n"] >= limit:
                    raise HostedUsageLimit("user" if column == "owner_user_id" else "ip")
            if operation == "revision":
                if audit_id is None:
                    raise ValueError("Revision usage requires an audit ID.")
                result = await conn.execute(
                    "SELECT count(*) AS n FROM provider_usage "
                    "WHERE audit_id=%s AND operation='revision'",
                    (audit_id,),
                )
                row = await result.fetchone()
                if row is not None and row["n"] >= self.AUDIT_REVISION_LIMIT:
                    raise HostedUsageLimit("audit_revision")
            await conn.execute(
                "INSERT INTO provider_usage "
                "(usage_id,owner_user_id,ip_hash,audit_id,provider,operation,status) "
                "VALUES (%s,%s,%s,%s,%s,%s,'started')",
                (identifier, owner_user_id, ip_hash, audit_id, provider, operation),
            )
        return identifier

    async def finish(
        self,
        usage_id: str,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        error_code: str | None = None,
    ) -> None:
        status = "failed" if error_code else "succeeded"
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE provider_usage SET status=%s,completed_at=now(),"
                "input_tokens=%s,output_tokens=%s,error_code=%s "
                "WHERE usage_id=%s AND status='started'",
                (status, input_tokens, output_tokens, error_code, usage_id),
            )


class MeteredProvider:
    """A vendor-neutral adapter; quota accounting never changes Jev's payload."""

    def __init__(
        self,
        provider: JudgmentProvider,
        guard: PostgresUsageGuard,
        owner_user_id: str,
        ip_hash: str,
        operation: Operation,
        *,
        audit_id: str | None = None,
        usage_id: str | None = None,
    ) -> None:
        self.provider = provider
        self.guard = guard
        self.owner_user_id = owner_user_id
        self.ip_hash = ip_hash
        self.operation = operation
        self.audit_id = audit_id
        self.usage_id = usage_id
        self.provider_name = provider.provider_name
        self.model_name = provider.model_name
        self.question_set_version = provider.question_set_version

    async def evaluate(
        self,
        claim: str,
        evidence: str,
        citation: str | None = None,
        *,
        revision_context: RevisionContext | None = None,
    ) -> JudgmentResult:
        usage_id = await self.guard.reserve(
            self.owner_user_id,
            self.ip_hash,
            self.provider_name,
            self.operation,
            audit_id=self.audit_id,
            usage_id=self.usage_id,
        )
        # No await between reservation and entry into the provider; a reached call
        # counts even if the provider later fails or the request is interrupted.
        try:
            result = await self.provider.evaluate(
                claim, evidence, citation, revision_context=revision_context
            )
        except asyncio.CancelledError:
            await asyncio.shield(self.guard.finish(usage_id, error_code="interrupted"))
            raise
        except TimeoutError:
            await self.guard.finish(usage_id, error_code="timeout")
            raise
        except ProviderError:
            await self.guard.finish(usage_id, error_code="provider_error")
            raise
        except Exception:
            await self.guard.finish(usage_id, error_code="evaluation_error")
            raise
        await self.guard.finish(
            usage_id, input_tokens=result.input_tokens, output_tokens=result.output_tokens
        )
        return result
