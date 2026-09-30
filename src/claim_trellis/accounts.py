"""Server-verified account metadata; Supabase Auth owns identity and credentials."""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from claim_trellis.auth import AuthPrincipal


class PostgresAccountProfiles:
    def __init__(self, pool: AsyncConnectionPool[AsyncConnection[dict[str, Any]]]) -> None:
        self.pool = pool

    async def get(self, user_id: str) -> dict[str, Any] | None:
        async with self.pool.connection() as conn:
            result = await conn.execute(
                "SELECT created_at,product_updates_opt_in FROM user_profiles WHERE user_id=%s",
                (user_id,),
            )
            return await result.fetchone()

    async def sync(self, identity: AuthPrincipal) -> dict[str, Any]:
        async with self.pool.connection() as conn:
            result = await conn.execute(
                "INSERT INTO user_profiles "
                "(user_id,user_email,email_verified,primary_auth_method,last_seen_at) "
                "VALUES (%s,%s,%s,%s,now()) "
                "ON CONFLICT (user_id) DO UPDATE SET "
                "user_email=EXCLUDED.user_email,email_verified=EXCLUDED.email_verified,"
                "primary_auth_method=EXCLUDED.primary_auth_method,"
                "updated_at=now(),last_seen_at=now() "
                "RETURNING created_at,product_updates_opt_in",
                (
                    identity.user_id,
                    identity.email if identity.email_verified else None,
                    identity.email_verified,
                    identity.primary_auth_method,
                ),
            )
            row = await result.fetchone()
            assert row is not None
            return row
