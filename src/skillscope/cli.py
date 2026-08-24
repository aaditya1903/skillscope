"""SkillScope command-line interface."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Never

import typer
import uvicorn
from pydantic import SecretStr
from rich.console import Console

from skillscope import __version__
from skillscope.core.config import get_settings
from skillscope.db.session import get_session_factory
from skillscope.ingestion.discovery import (
    MAX_DISCOVERY_PAGES_PER_QUERY,
    MAX_DISCOVERY_TARGET,
    build_discovery_plan,
    discover_skill_candidates,
    load_seed_repositories,
)
from skillscope.ingestion.github_client import GitHubClient, GitHubClientError
from skillscope.ingestion.manifest import (
    build_candidate_manifest,
    read_candidate_manifest,
    serialize_candidate_manifest,
    write_candidate_manifest,
)
from skillscope.ingestion.runner import run_ingestion
from skillscope.ingestion.snapshot import (
    build_dataset_snapshot,
    serialize_dataset_snapshot,
    write_dataset_snapshot,
)

DEFAULT_SEEDS_PATH = Path("data/seeds/repositories.txt")
DEFAULT_CANDIDATE_MANIFEST_PATH = Path("data/manifests/candidates.jsonl")
DEFAULT_DATASET_SNAPSHOT_PATH = Path("data/manifests/dataset-snapshot.jsonl")

app = typer.Typer(no_args_is_help=True, help="Operate the SkillScope observatory.")
ingest_app = typer.Typer(no_args_is_help=True, help="Discover and ingest public skills.")
app.add_typer(ingest_app, name="ingest")
console = Console()


@app.command()
def version() -> None:
    """Print the installed SkillScope version."""
    console.print(__version__)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Interface on which to listen."),
    port: int = typer.Option(8000, min=1, max=65535, help="TCP port."),
    reload: bool = typer.Option(False, help="Reload when source files change."),
) -> None:
    """Start the development API server."""
    uvicorn.run("skillscope.api.main:app", host=host, port=port, reload=reload)


@ingest_app.command("discover")
def ingest_discover(
    target_skills: Annotated[
        int,
        typer.Option(
            min=1,
            max=MAX_DISCOVERY_TARGET,
            help="Maximum number of unique public skills to retain.",
        ),
    ] = 100,
    seeds: Annotated[
        Path,
        typer.Option(help="UTF-8 file containing public owner/repository identifiers."),
    ] = DEFAULT_SEEDS_PATH,
    output: Annotated[
        Path,
        typer.Option(help="Relative JSONL path for the body-free candidate manifest."),
    ] = DEFAULT_CANDIDATE_MANIFEST_PATH,
    per_page: Annotated[
        int,
        typer.Option(min=1, max=100, help="GitHub results per page."),
    ] = 100,
    max_pages_per_query: Annotated[
        int,
        typer.Option(
            min=1,
            max=MAX_DISCOVERY_PAGES_PER_QUERY,
            help="Safety bound for each exact search query.",
        ),
    ] = MAX_DISCOVERY_PAGES_PER_QUERY,
    git_commit: Annotated[
        str | None,
        typer.Option(help="Full source commit, defaulting to the current Git HEAD."),
    ] = None,
) -> None:
    """Discover a deterministic public candidate sample through GitHub."""
    try:
        evidence = asyncio.run(
            _discover_candidates(
                target_skills=target_skills,
                seeds_path=seeds,
                output_path=output,
                per_page=per_page,
                max_pages_per_query=max_pages_per_query,
                git_commit=git_commit or _current_git_commit(),
            )
        )
    except GitHubClientError as error:
        _fail_safely(str(error))
    except ValueError as error:
        _fail_safely(str(error))
    _print_evidence(evidence)


@ingest_app.command("run")
def ingest_run(
    manifest: Annotated[
        Path,
        typer.Option(help="Relative candidate-manifest JSONL path."),
    ] = DEFAULT_CANDIDATE_MANIFEST_PATH,
    snapshot: Annotated[
        Path,
        typer.Option(help="Relative output path for the body-free dataset snapshot."),
    ] = DEFAULT_DATASET_SNAPSHOT_PATH,
    git_commit: Annotated[
        str | None,
        typer.Option(help="Full source commit, defaulting to the current Git HEAD."),
    ] = None,
    fail_on_errors: Annotated[
        bool,
        typer.Option(
            help="Return a failure exit code after safely writing evidence if any item errors."
        ),
    ] = False,
) -> None:
    """Fetch, parse, upsert, reconcile, and snapshot one candidate manifest."""
    try:
        evidence = asyncio.run(
            _run_candidate_manifest(
                manifest_path=manifest,
                snapshot_path=snapshot,
                git_commit=git_commit or _current_git_commit(),
            )
        )
    except GitHubClientError as error:
        _fail_safely(str(error))
    except ValueError as error:
        _fail_safely(str(error))
    _print_evidence(evidence)
    if fail_on_errors and evidence["error_count"]:
        raise typer.Exit(code=2)


async def _discover_candidates(
    *,
    target_skills: int,
    seeds_path: Path,
    output_path: Path,
    per_page: int,
    max_pages_per_query: int,
    git_commit: str,
) -> dict[str, object]:
    _validate_relative_jsonl_path(output_path)
    token = _github_token()
    plan = build_discovery_plan(load_seed_repositories(seeds_path))
    async with GitHubClient(token) as client:
        start_rate_limits = await client.get_rate_limits()
        result = await discover_skill_candidates(
            client,
            plan,
            target_skills=target_skills,
            per_page=per_page,
            max_pages_per_query=max_pages_per_query,
        )
        end_rate_limits = await client.get_rate_limits()

    manifest = build_candidate_manifest(
        result,
        generated_at=datetime.now(UTC),
        git_commit=git_commit,
    )
    write_candidate_manifest(output_path, manifest)
    serialized = serialize_candidate_manifest(manifest)
    return {
        "operation": "discover",
        "manifest_path": output_path.as_posix(),
        "manifest_sha256": hashlib.sha256(serialized).hexdigest(),
        "manifest_bytes": len(serialized),
        "target_skills": result.target_skills,
        "target_reached": result.target_reached,
        "candidate_count": result.candidate_count,
        "page_count": len(result.pages),
        "repository_count": len({candidate.repository_id for candidate in result.candidates}),
        "queries": list(result.plan.queries),
        "code_search_remaining_before": (start_rate_limits.data.resources.code_search.remaining),
        "code_search_remaining_after": end_rate_limits.data.resources.code_search.remaining,
    }


async def _run_candidate_manifest(
    *,
    manifest_path: Path,
    snapshot_path: Path,
    git_commit: str,
) -> dict[str, object]:
    _validate_relative_jsonl_path(manifest_path)
    _validate_relative_jsonl_path(snapshot_path)
    token = _github_token()
    candidate_manifest = read_candidate_manifest(manifest_path)
    session_factory = get_session_factory()
    async with GitHubClient(token) as client:
        summary = await run_ingestion(
            client,
            session_factory,
            candidate_manifest,
            manifest_path=manifest_path,
            git_commit_sha=git_commit,
        )

    with session_factory() as session:
        dataset_snapshot = build_dataset_snapshot(
            session,
            candidate_manifest,
            ingestion_run_id=summary.run_id,
            candidate_manifest_path=manifest_path,
            generated_at=datetime.now(UTC),
            git_commit=git_commit,
        )
    write_dataset_snapshot(snapshot_path, dataset_snapshot)
    serialized_snapshot = serialize_dataset_snapshot(dataset_snapshot)
    failures = [
        {
            "repository": outcome.repository_full_name,
            "path": outcome.path,
            "status": outcome.status.value,
            "reason": json.loads(outcome.reason) if outcome.reason is not None else None,
        }
        for outcome in summary.outcomes
        if outcome.reason is not None
    ]
    return {
        "operation": "ingest",
        "run_id": str(summary.run_id),
        "manifest_path": manifest_path.as_posix(),
        "snapshot_path": snapshot_path.as_posix(),
        "snapshot_sha256": hashlib.sha256(serialized_snapshot).hexdigest(),
        "snapshot_bytes": len(serialized_snapshot),
        "candidate_count": dataset_snapshot.header.candidate_count,
        "repository_count": dataset_snapshot.header.repository_count,
        "stored_skill_count": dataset_snapshot.header.stored_skill_count,
        "ingested_count": summary.ingested_count,
        "unchanged_count": summary.unchanged_count,
        "invalid_count": summary.invalid_count,
        "skipped_count": summary.skipped_count,
        "error_count": summary.error_count,
        "failures": failures,
    }


def _github_token() -> SecretStr:
    token = get_settings().github_token
    if token is None or not token.get_secret_value().strip():
        raise ValueError("GITHUB_TOKEN is not configured in the local .env file")
    return token


def _current_git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip().lower()


def _print_evidence(evidence: dict[str, object]) -> None:
    console.print_json(json.dumps(evidence, ensure_ascii=False, sort_keys=True))


def _validate_relative_jsonl_path(path: Path) -> None:
    if path.is_absolute() or path.suffix != ".jsonl" or ".." in path.parts:
        raise ValueError("manifest paths must be safe relative JSONL paths")
    normalized = path.as_posix()
    if not normalized or normalized.startswith("./"):
        raise ValueError("manifest paths must be normalized")


def _fail_safely(message: str) -> Never:
    console.print(f"Error: {message}", style="bold red")
    raise typer.Exit(code=1)


def main() -> None:
    """Run the command-line application."""
    app()


if __name__ == "__main__":
    main()
