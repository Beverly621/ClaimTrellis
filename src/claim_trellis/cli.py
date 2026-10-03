from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer
import uvicorn
from psycopg import Error as PostgresError
from rich.console import Console

from claim_trellis.audit import run_audit
from claim_trellis.benchmark_runner import run_cases, write_predictions
from claim_trellis.config import get_settings
from claim_trellis.ingestion import parse_document_bytes
from claim_trellis.metrics import (
    BenchmarkCase,
    Prediction,
    read_jsonl,
    score_predictions,
    validate_benchmark,
    write_json,
)
from claim_trellis.migrations import migrate, migration_status
from claim_trellis.models import AuditRequest, SourceAccessTier, SourceMetadata

app = typer.Typer(no_args_is_help=True, help="Auditable claim-to-source verification.")
benchmark_app = typer.Typer(no_args_is_help=True, help="Validate and score benchmark files.")
db_app = typer.Typer(no_args_is_help=True, help="Inspect and apply PostgreSQL migrations.")
app.add_typer(benchmark_app, name="benchmark")
app.add_typer(db_app, name="db")
console = Console()


@app.command()
def serve(
    host: str | None = typer.Option(None, help="Bind host; defaults to CLAIM_TRELLIS_HOST."),
    port: int | None = typer.Option(
        None, min=1, max=65535, help="Bind port; defaults to CLAIM_TRELLIS_PORT."
    ),
    reload: bool = typer.Option(False, help="Enable development reload."),
) -> None:
    settings = get_settings()
    uvicorn.run(
        "claim_trellis.api:app",
        host=host or settings.host,
        port=port or settings.port,
        reload=reload,
    )


@app.command("audit")
def audit_command(
    claim: str = typer.Option(..., help="One atomic English claim."),
    source: Path = typer.Option(..., exists=True, readable=True, dir_okay=False),
    citation: str | None = typer.Option(None, help="DOI, PMID, URL, or bibliographic label."),
    quote: str | None = typer.Option(None, help="Optional exact quote to verify."),
    access_tier: SourceAccessTier = typer.Option(SourceAccessTier.FULL_TEXT),
    no_provider: bool = typer.Option(
        False, help="Run deterministic checks without a structured judgment provider."
    ),
) -> None:
    settings = get_settings()
    document = parse_document_bytes(
        source.name,
        source.read_bytes(),
        max_bytes=settings.max_upload_bytes,
        max_chars=settings.max_source_chars,
    )
    request = AuditRequest(
        claim=claim,
        source_text=document.text,
        source_blocks=document.blocks,
        citation=citation,
        quote=quote,
        source=SourceMetadata(access_tier=access_tier, content_sha256=document.content_sha256),
        use_judgment_provider=not no_provider,
    )
    result = asyncio.run(run_audit(request, settings))
    console.print_json(result.model_dump_json())


@benchmark_app.command("validate")
def benchmark_validate(
    path: Path = typer.Argument(..., exists=True, readable=True, dir_okay=False),
) -> None:
    console.print_json(write_json(validate_benchmark(path)))


@benchmark_app.command("score")
def benchmark_score(
    gold: Path = typer.Argument(..., exists=True, readable=True, dir_okay=False),
    predictions: Path = typer.Argument(..., exists=True, readable=True, dir_okay=False),
) -> None:
    cases = [BenchmarkCase.model_validate(item) for item in read_jsonl(gold, BenchmarkCase)]
    predicted = [Prediction.model_validate(item) for item in read_jsonl(predictions, Prediction)]
    console.print_json(json.dumps(score_predictions(cases, predicted), indent=2, sort_keys=True))


@benchmark_app.command("run")
def benchmark_run(
    gold: Path = typer.Argument(..., exists=True, readable=True, dir_okay=False),
    output: Path = typer.Option(
        Path("reports/local/predictions.jsonl"),
        help="Local output path; reports/local is ignored by Git.",
    ),
    concurrency: int = typer.Option(8, min=1, max=64),
) -> None:
    """Run the pinned default-provider question set and print evaluation metrics."""

    settings = get_settings()
    cases = [BenchmarkCase.model_validate(item) for item in read_jsonl(gold, BenchmarkCase)]
    predictions = asyncio.run(run_cases(cases, settings, concurrency=concurrency))
    write_predictions(output, predictions)
    report = score_predictions(cases, predictions)
    report["usage"] = {
        "input_tokens_uncached": sum(item.input_tokens for item in predictions if not item.cached),
        "output_tokens_uncached": sum(
            item.output_tokens for item in predictions if not item.cached
        ),
        "cached_cases": sum(item.cached for item in predictions),
        "output": str(output),
    }
    console.print_json(json.dumps(report, indent=2, sort_keys=True))


@app.command("doctor")
def doctor() -> None:
    settings = get_settings()
    checks = {
        "python": "ok",
        "storage_backend": settings.selected_storage_backend,
        "database_configured": bool(settings.database_url)
        if settings.selected_storage_backend == "postgres"
        else True,
        "auth_mode": settings.auth_mode,
        "supabase_auth_configured": bool(
            settings.supabase_url and settings.supabase_publishable_key
        ),
        "provider_configured": bool(settings.jev_api_key),
    }
    console.print_json(json.dumps(checks, indent=2))


def _database_url() -> str:
    value = get_settings().database_url
    if not value:
        console.print("DATABASE_URL is not configured.")
        raise typer.Exit(1)
    return value


@db_app.command("status")
def db_status() -> None:
    try:
        result = asyncio.run(migration_status(_database_url()))
    except (PostgresError, OSError):
        console.print(
            "Could not inspect PostgreSQL migrations. Check connectivity and credentials."
        )
        raise typer.Exit(1) from None
    for name, applied in result:
        console.print(f"{name}: {'applied' if applied else 'pending'}")


@db_app.command("migrate")
def db_migrate() -> None:
    try:
        applied = asyncio.run(migrate(_database_url()))
    except (PostgresError, OSError):
        console.print("PostgreSQL migration failed. No credentials were printed.")
        raise typer.Exit(1) from None
    console.print("Applied: " + (", ".join(applied) if applied else "none; already current"))


if __name__ == "__main__":
    app()
