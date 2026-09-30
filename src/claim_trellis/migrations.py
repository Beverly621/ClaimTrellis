"""Explicit, source-controlled PostgreSQL migrations."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo

MIGRATION_NAMES = ("0001_persistence.sql",)


def _migration_text(name: str) -> str:
    packaged = files("claim_trellis").joinpath("migrations", "postgres", name)
    if packaged.is_file():
        return packaged.read_text()
    return (Path(__file__).resolve().parents[2] / "migrations" / "postgres" / name).read_text()


async def migration_status(
    database_url: str, *, sslmode: str = "require"
) -> list[tuple[str, bool]]:
    conninfo = make_conninfo(database_url, sslmode=sslmode)
    async with await psycopg.AsyncConnection.connect(conninfo, prepare_threshold=None) as conn:
        result = await conn.execute("SELECT to_regclass('public.claim_trellis_schema_migrations')")
        row = await result.fetchone()
        exists = row is not None and row[0] is not None
        applied: set[str] = set()
        if exists:
            rows = await conn.execute("SELECT migration_id FROM claim_trellis_schema_migrations")
            applied = {row[0] for row in await rows.fetchall()}
        return [(name, name in applied) for name in MIGRATION_NAMES]


async def migrate(database_url: str, *, sslmode: str = "require") -> list[str]:
    """Apply each migration once; migration SQL and tracking commit together."""

    conninfo = make_conninfo(database_url, sslmode=sslmode)
    applied: list[str] = []
    async with await psycopg.AsyncConnection.connect(conninfo, prepare_threshold=None) as conn:
        for name in MIGRATION_NAMES:
            async with conn.transaction():
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtext('claim_trellis_migrations'))"
                )
                await conn.execute(
                    "CREATE TABLE IF NOT EXISTS claim_trellis_schema_migrations "
                    "(migration_id TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
                )
                result = await conn.execute(
                    "SELECT 1 FROM claim_trellis_schema_migrations WHERE migration_id=%s",
                    (name,),
                )
                if await result.fetchone() is not None:
                    continue
                # The checked-in migration consists of plain DDL statements.
                # Execute separately for transaction-pooler/extended-protocol safety.
                for statement in _migration_text(name).split(";"):
                    if statement.strip():
                        await conn.execute(statement)
                await conn.execute(
                    "INSERT INTO claim_trellis_schema_migrations (migration_id) VALUES (%s)",
                    (name,),
                )
                applied.append(name)
    return applied
