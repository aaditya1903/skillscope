"""Unit tests for body-free ingestion summaries and reconciliation."""

from uuid import uuid4

import pytest

from skillscope.db.enums import IngestionItemStatus
from skillscope.ingestion.runner import IngestionItemOutcome, IngestionSummary


def _outcome(
    status: IngestionItemStatus,
    *,
    fetched: bool,
    parsed: bool,
) -> IngestionItemOutcome:
    return IngestionItemOutcome(
        repository_full_name="skillscope-tests/catalogue",
        path=f"skills/{status.value}/SKILL.md",
        status=status,
        reason=None,
        content_sha256="a" * 64,
        duration_ms=1,
        fetched=fetched,
        parsed=parsed,
    )


def test_summary_reconciles_item_level_evidence() -> None:
    outcomes = (
        _outcome(IngestionItemStatus.INGESTED, fetched=True, parsed=True),
        _outcome(IngestionItemStatus.UNCHANGED, fetched=False, parsed=False),
        _outcome(IngestionItemStatus.INVALID, fetched=True, parsed=True),
        _outcome(IngestionItemStatus.ERROR, fetched=False, parsed=False),
        _outcome(IngestionItemStatus.SKIPPED, fetched=False, parsed=False),
    )
    summary = IngestionSummary(
        run_id=uuid4(),
        discovered_count=5,
        fetched_count=2,
        unchanged_count=1,
        parsed_count=2,
        invalid_count=1,
        error_count=1,
        outcomes=outcomes,
    )

    summary.reconcile()

    assert summary.ingested_count == 1
    assert summary.skipped_count == 1


def test_summary_rejects_a_counter_that_does_not_match_items() -> None:
    outcome = _outcome(IngestionItemStatus.INGESTED, fetched=True, parsed=True)
    summary = IngestionSummary(
        run_id=uuid4(),
        discovered_count=1,
        fetched_count=0,
        unchanged_count=0,
        parsed_count=1,
        invalid_count=0,
        error_count=0,
        outcomes=(outcome,),
    )

    with pytest.raises(RuntimeError, match="fetched count"):
        summary.reconcile()
