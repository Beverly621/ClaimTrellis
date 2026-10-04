"""Backup/restore rehearsals on databases created by this test, never production."""

import json
import os
import shutil
import subprocess
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from test_postgres_store import USER_A, opened, pg_url
from test_storage import example_audit

from claim_trellis import migrations

__all__ = ["pg_url"]


def pg_tool(name, url, *, input_data=None):
    info = conninfo_to_dict(url)
    assert info["dbname"].startswith("claim_trellis_p17_") and info["dbname"].endswith("_test")
    if shutil.which(name):
        env = os.environ.copy()
        env.update(
            PGHOST=info["host"],
            PGPORT=info.get("port", "5432"),
            PGUSER=info["user"],
            PGPASSWORD=info["password"],
            PGDATABASE=info["dbname"],
            PGSSLMODE="disable",
        )
        command = [name]
    else:
        container = os.environ.get("TEST_PG_CONTAINER", "")
        if not container:
            pytest.fail(
                "Install pg_dump/pg_restore or set TEST_PG_CONTAINER to the labeled disposable test container."
            )
        labels = json.loads(
            subprocess.check_output(
                ["docker", "inspect", container, "--format", "{{json .Config.Labels}}"], text=True
            )
        )
        assert labels.get("claim-trellis.task") == "p17-acceptance"
        command = ["docker", "exec", "-i", container, name, "-U", info["user"]]
        env = os.environ.copy()
    if name == "pg_dump":
        command += ["--format=custom", "--no-owner", info["dbname"]]
    else:
        command += ["--exit-on-error", "--no-owner", "--dbname", info["dbname"]]
    result = subprocess.run(
        command,
        input=input_data,
        capture_output=True,
        env=env,
        timeout=60,
    )
    # No connection strings or raw dump/error contents in CI output.
    assert result.returncode == 0, (
        f"{name} failed (exit {result.returncode}); inspect sanitized diagnostics locally."
    )
    return result.stdout


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "initial_count",
    [3, 5],
    ids=["existing-0003-upgrade-and-preupgrade-restore", "fresh-0001-to-0005-and-restore"],
)
async def test_fresh_upgrade_backup_restore_rehearsal(pg_url, monkeypatch, tmp_path, initial_count):
    names = [f"claim_trellis_p17_{uuid4().hex}_{role}_test" for role in ("before", "restore")]
    admin = make_conninfo(pg_url, dbname="postgres", sslmode="disable")
    urls = [make_conninfo(pg_url, dbname=name, sslmode="disable") for name in names]
    all_names = migrations.MIGRATION_NAMES
    created = []
    try:
        with psycopg.connect(admin, autocommit=True) as conn:
            for name in names:
                conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
                created.append(name)
        with monkeypatch.context() as context:
            context.setattr(migrations, "MIGRATION_NAMES", all_names[:initial_count])
            assert await migrations.migrate(urls[0], sslmode="disable") == list(
                all_names[:initial_count]
            )
        store = await opened(urls[0])
        audit = example_audit().model_copy(update={"audit_id": str(uuid4())})
        await store.save(USER_A, audit)
        await store.close()
        dump = pg_tool("pg_dump", urls[0])
        assert dump.startswith(b"PGDMP")
        backup = tmp_path / "synthetic-rehearsal.dump"
        backup.write_bytes(dump)
        backup.chmod(0o600)
        assert await migrations.migrate(urls[0], sslmode="disable") == list(
            all_names[initial_count:]
        )
        # Recovery to the pre-migration backup is a new disposable database, not
        # destructive down-migration. The original remains available for comparison.
        pg_tool("pg_restore", urls[1], input_data=backup.read_bytes())
        assert await migrations.migration_status(urls[1], sslmode="disable") == [
            (name, i < initial_count) for i, name in enumerate(all_names)
        ]
        for url in urls:
            store = await opened(url)
            assert await store.get(USER_A, audit.audit_id) == audit
            assert await store.get(str(uuid4()), audit.audit_id) is None
            assert len(await store.events(USER_A, audit.audit_id)) > 0
            await store.close()
        assert await migrations.migrate(urls[1], sslmode="disable") == list(
            all_names[initial_count:]
        )
        assert await migrations.migrate(urls[1], sslmode="disable") == []
        with psycopg.connect(urls[1]) as conn:
            rows = conn.execute(
                "SELECT tablename,rowsecurity FROM pg_tables WHERE schemaname='public'"
            ).fetchall()
            assert len(rows) == 14
            assert all(rls for table, rls in rows if table != "claim_trellis_schema_migrations")
            for table, _ in rows:
                if table == "claim_trellis_schema_migrations":
                    continue
                for role in ("anon", "authenticated"):
                    assert not conn.execute(
                        "SELECT has_table_privilege(%s,%s,'SELECT,INSERT,UPDATE,DELETE')",
                        (role, "public." + table),
                    ).fetchone()[0]
    finally:
        # Only exact UUID-named databases created by this test are removed.
        with psycopg.connect(admin, autocommit=True) as conn:
            for name in created:
                conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
