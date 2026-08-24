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
from skillscope.db.enums import EvaluationSplit
from skillscope.db.session import get_session_factory
from skillscope.evaluation.config import EvaluationConfig, load_evaluation_config
from skillscope.evaluation.data import (
    EvaluationDataError,
    QuerySet,
    read_qrel_set,
    read_query_set,
    serialize_qrel_set,
    serialize_query_set,
    sha256_bytes,
    validate_evaluation_dataset,
    write_qrel_set,
)
from skillscope.evaluation.pooling import (
    CandidatePool,
    build_bm25_candidate_pool,
    qrels_from_label_worksheet,
    read_candidate_pool,
    serialize_candidate_pool,
    write_candidate_pool,
    write_label_worksheet,
)
from skillscope.evaluation.runner import (
    evaluate_bm25,
    serialize_evaluation_report,
    write_evaluation_report,
)
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
from skillscope.retrieval.bm25 import BM25Index
from skillscope.retrieval.config import load_bm25_config
from skillscope.retrieval.corpus import CorpusIntegrityError, load_frozen_corpus
from skillscope.retrieval.text import normalize_lexical_text, tokenize

DEFAULT_SEEDS_PATH = Path("data/seeds/repositories.txt")
DEFAULT_CANDIDATE_MANIFEST_PATH = Path("data/manifests/candidates.jsonl")
DEFAULT_DATASET_SNAPSHOT_PATH = Path("data/manifests/dataset-snapshot.jsonl")
DEFAULT_BM25_CONFIG_PATH = Path("config/retrieval/bm25-v1.json")
DEFAULT_EVALUATION_CONFIG_PATH = Path("config/evaluation/evaluation-v1.json")
DEFAULT_LABEL_WORKSHEET_PATH = Path("/tmp/skillscope-m7-labels.csv")
DEFAULT_DEVELOPMENT_REPORT_PATH = Path("reports/evaluation/bm25-development-v1.json")

app = typer.Typer(no_args_is_help=True, help="Operate the SkillScope observatory.")
ingest_app = typer.Typer(no_args_is_help=True, help="Discover and ingest public skills.")
evaluation_app = typer.Typer(
    no_args_is_help=True,
    help="Build and run frozen retrieval evaluations.",
)
app.add_typer(ingest_app, name="ingest")
app.add_typer(evaluation_app, name="evaluate")
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


@app.command("search")
def search_bm25(
    query: Annotated[
        str,
        typer.Argument(help="Lexical query to run against the frozen corpus."),
    ],
    top_k: Annotated[
        int | None,
        typer.Option(min=1, max=100, help="Maximum results; defaults to the baseline config."),
    ] = None,
    config: Annotated[
        Path,
        typer.Option(help="Versioned BM25 baseline configuration."),
    ] = DEFAULT_BM25_CONFIG_PATH,
    snapshot: Annotated[
        Path | None,
        typer.Option(help="Optional snapshot path override, still checked against its saved hash."),
    ] = None,
) -> None:
    """Search the frozen corpus with deterministic, explained BM25 ranking."""

    try:
        evidence = _search_bm25(
            query=query,
            top_k=top_k,
            config_path=config,
            snapshot_path=snapshot,
        )
    except (CorpusIntegrityError, ValueError) as error:
        _fail_safely(str(error))
    _print_evidence(evidence)


@evaluation_app.command("pool")
def evaluation_pool(
    config: Annotated[
        Path,
        typer.Option(help="Versioned retrieval-evaluation configuration."),
    ] = DEFAULT_EVALUATION_CONFIG_PATH,
    worksheet: Annotated[
        Path,
        typer.Option(help="Rank-blinded CSV worksheet written outside committed evidence."),
    ] = DEFAULT_LABEL_WORKSHEET_PATH,
) -> None:
    """Pool BM25 results and authored seeds into a blinded labelling worksheet."""

    try:
        evidence = _build_evaluation_pool(config_path=config, worksheet_path=worksheet)
    except (CorpusIntegrityError, EvaluationDataError, ValueError) as error:
        _fail_safely(str(error))
    _print_evidence(evidence)


@evaluation_app.command("import-labels")
def evaluation_import_labels(
    worksheet: Annotated[
        Path,
        typer.Argument(help="Completed rank-blinded CSV worksheet."),
    ],
    config: Annotated[
        Path,
        typer.Option(help="Versioned retrieval-evaluation configuration."),
    ] = DEFAULT_EVALUATION_CONFIG_PATH,
) -> None:
    """Validate a completed worksheet and write canonical qrel JSONL."""

    try:
        evidence = _import_evaluation_labels(config_path=config, worksheet_path=worksheet)
    except (CorpusIntegrityError, EvaluationDataError, ValueError) as error:
        _fail_safely(str(error))
    _print_evidence(evidence)


@evaluation_app.command("validate")
def evaluation_validate(
    config: Annotated[
        Path,
        typer.Option(help="Versioned retrieval-evaluation configuration."),
    ] = DEFAULT_EVALUATION_CONFIG_PATH,
) -> None:
    """Cross-check query, qrel, pool, snapshot, and live skill identities."""

    try:
        evidence = _validate_evaluation_files(config_path=config)
    except (CorpusIntegrityError, EvaluationDataError, ValueError) as error:
        _fail_safely(str(error))
    _print_evidence(evidence)


@evaluation_app.command("bm25")
def evaluation_bm25(
    split: Annotated[
        EvaluationSplit,
        typer.Option(help="Frozen query split to evaluate."),
    ] = EvaluationSplit.DEVELOPMENT,
    allow_test: Annotated[
        bool,
        typer.Option(help="Explicitly unlock the test split for the final method comparison."),
    ] = False,
    output: Annotated[
        Path,
        typer.Option(help="Canonical JSON evaluation report path."),
    ] = DEFAULT_DEVELOPMENT_REPORT_PATH,
    config: Annotated[
        Path,
        typer.Option(help="Versioned retrieval-evaluation configuration."),
    ] = DEFAULT_EVALUATION_CONFIG_PATH,
) -> None:
    """Evaluate BM25 while keeping test metrics locked by default."""

    try:
        evidence = _evaluate_bm25_split(
            config_path=config,
            split=split,
            allow_test=allow_test,
            output_path=output,
            git_commit=_current_git_commit(),
        )
    except (CorpusIntegrityError, EvaluationDataError, ValueError) as error:
        _fail_safely(str(error))
    _print_evidence(evidence)


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


def _search_bm25(
    *,
    query: str,
    top_k: int | None,
    config_path: Path,
    snapshot_path: Path | None,
) -> dict[str, object]:
    baseline = load_bm25_config(config_path)
    session_factory = get_session_factory()
    with session_factory() as session:
        corpus = load_frozen_corpus(session, baseline, snapshot_path=snapshot_path)
    index = BM25Index(corpus, baseline)
    results = index.search(query, top_k=top_k)
    return {
        "operation": "search",
        "method": baseline.method,
        "query": query,
        "normalized_query": normalize_lexical_text(query),
        "query_terms": list(dict.fromkeys(tokenize(query))),
        "snapshot_path": corpus.snapshot_path,
        "snapshot_sha256": corpus.snapshot_sha256,
        "corpus_size": index.document_count,
        "average_document_length": index.average_document_length,
        "k1": baseline.k1,
        "b": baseline.b,
        "results": [
            {
                "rank": rank,
                "document_id": result.document.document_id,
                "skill_id": str(result.document.skill_id),
                "repository": result.document.repository_full_name,
                "path": result.document.path,
                "name": result.document.name,
                "snippet": result.document.safe_snippet,
                "validation_status": result.document.validation_status.value,
                "score": result.score,
                "matched_terms": list(result.matched_terms),
                "term_scores": [
                    {
                        "term": term.term,
                        "term_frequency": term.term_frequency,
                        "document_frequency": term.document_frequency,
                        "inverse_document_frequency": term.inverse_document_frequency,
                        "score": term.score,
                    }
                    for term in result.term_scores
                ],
            }
            for rank, result in enumerate(results, start=1)
        ],
    }


def _build_evaluation_pool(
    *,
    config_path: Path,
    worksheet_path: Path,
) -> dict[str, object]:
    evaluation_config = load_evaluation_config(config_path)
    query_set, query_set_sha256 = _load_frozen_query_set(evaluation_config)
    index, _ = _load_evaluation_index(evaluation_config)
    pool = build_bm25_candidate_pool(
        index,
        query_set,
        query_set_path=evaluation_config.query_set_path,
        query_set_sha256=query_set_sha256,
        pool_depth=evaluation_config.pool_depth,
    )
    pool_path = Path(evaluation_config.candidate_pool_path)
    write_candidate_pool(pool_path, pool)
    serialized_pool = serialize_candidate_pool(pool)
    pool_sha256 = sha256_bytes(serialized_pool)
    write_label_worksheet(
        worksheet_path,
        pool,
        query_set,
        candidate_pool_sha256=pool_sha256,
    )
    serialized_worksheet = worksheet_path.read_bytes()
    return {
        "operation": "evaluation_pool",
        "query_set_path": evaluation_config.query_set_path,
        "query_set_sha256": query_set_sha256,
        "query_count": query_set.header.query_count,
        "development_count": query_set.header.development_count,
        "test_count": query_set.header.test_count,
        "candidate_pool_path": pool_path.as_posix(),
        "candidate_pool_sha256": pool_sha256,
        "candidate_count": pool.header.item_count,
        "pool_depth": pool.header.pool_depth,
        "worksheet_path": worksheet_path.as_posix(),
        "worksheet_sha256": sha256_bytes(serialized_worksheet),
        "worksheet_bytes": len(serialized_worksheet),
        "rank_blinded": True,
        "test_metrics_computed": False,
    }


def _import_evaluation_labels(
    *,
    config_path: Path,
    worksheet_path: Path,
) -> dict[str, object]:
    evaluation_config = load_evaluation_config(config_path)
    query_set, query_set_sha256 = _load_frozen_query_set(evaluation_config)
    pool, pool_sha256 = _load_frozen_candidate_pool(evaluation_config, query_set_sha256)
    qrels = qrels_from_label_worksheet(
        worksheet_path,
        pool,
        query_set,
        query_set_path=evaluation_config.query_set_path,
        candidate_pool_path=evaluation_config.candidate_pool_path,
        candidate_pool_sha256=pool_sha256,
    )
    index, _ = _load_evaluation_index(evaluation_config)
    validate_evaluation_dataset(
        query_set,
        qrels,
        query_set_sha256=query_set_sha256,
        available_documents={
            document.document_id: document.content_sha256 for document in index.documents
        },
    )
    qrels_path = Path(evaluation_config.qrels_path)
    write_qrel_set(qrels_path, qrels)
    serialized_qrels = serialize_qrel_set(qrels)
    return {
        "operation": "evaluation_import_labels",
        "qrels_path": qrels_path.as_posix(),
        "qrels_sha256": sha256_bytes(serialized_qrels),
        "query_count": qrels.header.query_count,
        "judgement_count": qrels.header.judgement_count,
        "relevant_judgement_count": qrels.header.relevant_judgement_count,
        "missing_document_ids": 0,
        "test_metrics_computed": False,
    }


def _validate_evaluation_files(*, config_path: Path) -> dict[str, object]:
    evaluation_config = load_evaluation_config(config_path)
    query_set, query_set_sha256 = _load_frozen_query_set(evaluation_config)
    _, pool_sha256 = _load_frozen_candidate_pool(evaluation_config, query_set_sha256)
    qrels_path = Path(evaluation_config.qrels_path)
    qrels = read_qrel_set(qrels_path)
    serialized_qrels = serialize_qrel_set(qrels)
    if qrels.header.candidate_pool_sha256 != pool_sha256:
        raise EvaluationDataError("qrels reference different candidate-pool bytes")
    index, _ = _load_evaluation_index(evaluation_config)
    validate_evaluation_dataset(
        query_set,
        qrels,
        query_set_sha256=query_set_sha256,
        available_documents={
            document.document_id: document.content_sha256 for document in index.documents
        },
    )
    return {
        "operation": "evaluation_validate",
        "query_set_sha256": query_set_sha256,
        "candidate_pool_sha256": pool_sha256,
        "qrels_sha256": sha256_bytes(serialized_qrels),
        "query_count": query_set.header.query_count,
        "development_count": query_set.header.development_count,
        "test_count": query_set.header.test_count,
        "judgement_count": qrels.header.judgement_count,
        "relevant_judgement_count": qrels.header.relevant_judgement_count,
        "corpus_document_count": index.document_count,
        "missing_document_ids": 0,
        "test_metrics_computed": False,
    }


def _evaluate_bm25_split(
    *,
    config_path: Path,
    split: EvaluationSplit,
    allow_test: bool,
    output_path: Path,
    git_commit: str,
) -> dict[str, object]:
    evaluation_config = load_evaluation_config(config_path)
    query_set, query_set_sha256 = _load_frozen_query_set(evaluation_config)
    _, pool_sha256 = _load_frozen_candidate_pool(evaluation_config, query_set_sha256)
    qrels_path = Path(evaluation_config.qrels_path)
    qrels = read_qrel_set(qrels_path)
    serialized_qrels = serialize_qrel_set(qrels)
    qrels_sha256 = sha256_bytes(serialized_qrels)
    if qrels.header.candidate_pool_sha256 != pool_sha256:
        raise EvaluationDataError("qrels reference different candidate-pool bytes")
    index, bm25_config_sha256 = _load_evaluation_index(evaluation_config)
    validate_evaluation_dataset(
        query_set,
        qrels,
        query_set_sha256=query_set_sha256,
        available_documents={
            document.document_id: document.content_sha256 for document in index.documents
        },
    )
    report = evaluate_bm25(
        index,
        query_set,
        qrels,
        split=split,
        generated_at=datetime.now(UTC),
        git_commit=git_commit,
        query_set_sha256=query_set_sha256,
        qrels_sha256=qrels_sha256,
        bm25_config_sha256=bm25_config_sha256,
        allow_test=allow_test,
    )
    write_evaluation_report(output_path, report)
    serialized_report = serialize_evaluation_report(report)
    return {
        "operation": "evaluation_bm25",
        "split": split.value,
        "report_path": output_path.as_posix(),
        "report_sha256": sha256_bytes(serialized_report),
        "query_count": report.query_count,
        "ndcg_at_10": report.ndcg_at_10,
        "mrr_at_10": report.mrr_at_10,
        "recall_at_10": report.recall_at_10,
        "failure_examples": [
            example.model_dump(mode="json") for example in report.failure_examples
        ],
    }


def _load_frozen_query_set(config: EvaluationConfig) -> tuple[QuerySet, str]:
    query_set_path = Path(config.query_set_path)
    query_set = read_query_set(query_set_path)
    query_set_sha256 = sha256_bytes(serialize_query_set(query_set))
    if query_set_sha256 != config.query_set_sha256:
        raise EvaluationDataError("query-set SHA-256 differs from evaluation configuration")
    if query_set.header.corpus_snapshot_path != config.corpus_snapshot_path:
        raise EvaluationDataError("query set and evaluation config use different snapshot paths")
    if query_set.header.corpus_snapshot_sha256 != config.corpus_snapshot_sha256:
        raise EvaluationDataError("query set and evaluation config use different snapshot bytes")
    return query_set, query_set_sha256


def _load_frozen_candidate_pool(
    config: EvaluationConfig,
    query_set_sha256: str,
) -> tuple[CandidatePool, str]:
    pool_path = Path(config.candidate_pool_path)
    pool = read_candidate_pool(pool_path)
    pool_sha256 = sha256_bytes(serialize_candidate_pool(pool))
    if pool.header.query_set_sha256 != query_set_sha256:
        raise EvaluationDataError("candidate pool references different query-set bytes")
    if pool.header.corpus_snapshot_sha256 != config.corpus_snapshot_sha256:
        raise EvaluationDataError("candidate pool references different snapshot bytes")
    if pool.header.pool_depth != config.pool_depth:
        raise EvaluationDataError("candidate pool depth differs from evaluation configuration")
    return pool, pool_sha256


def _load_evaluation_index(config: EvaluationConfig) -> tuple[BM25Index, str]:
    bm25_config_path = Path(config.bm25_config_path)
    bm25_config_bytes = bm25_config_path.read_bytes()
    bm25_config_sha256 = sha256_bytes(bm25_config_bytes)
    baseline = load_bm25_config(bm25_config_path)
    if baseline.corpus_snapshot_path != config.corpus_snapshot_path:
        raise EvaluationDataError("BM25 and evaluation configs use different snapshot paths")
    if baseline.corpus_snapshot_sha256 != config.corpus_snapshot_sha256:
        raise EvaluationDataError("BM25 and evaluation configs use different snapshot bytes")
    session_factory = get_session_factory()
    with session_factory() as session:
        corpus = load_frozen_corpus(session, baseline)
    return BM25Index(corpus, baseline), bm25_config_sha256


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
