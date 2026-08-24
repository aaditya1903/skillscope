"""Hand-calculated nDCG, MRR, and Recall tests."""

import math

import pytest

from skillscope.evaluation.metrics import (
    discounted_cumulative_gain,
    evaluate_rankings,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank_at_k,
)


def test_dcg_matches_a_hand_calculation() -> None:
    expected = 3.0 + 1.0 / math.log2(3.0)

    assert discounted_cumulative_gain((2, 1, 0), cutoff=3) == pytest.approx(expected)


def test_ndcg_is_one_for_ideal_ranking() -> None:
    qrels = {"a": 2, "b": 1, "c": 0}

    assert ndcg_at_k(("a", "b", "c"), qrels, cutoff=3) == pytest.approx(1.0)


def test_ndcg_matches_a_nonideal_hand_calculation() -> None:
    qrels = {"a": 2, "b": 1, "c": 0}
    actual = 1.0 + 3.0 / math.log2(3.0)
    ideal = 3.0 + 1.0 / math.log2(3.0)

    assert ndcg_at_k(("b", "a", "c"), qrels, cutoff=3) == pytest.approx(actual / ideal)


def test_ndcg_treats_unjudged_results_as_nonrelevant() -> None:
    assert ndcg_at_k(("unknown", "relevant"), {"relevant": 2}, cutoff=2) == pytest.approx(
        1.0 / math.log2(3.0)
    )


def test_reciprocal_rank_uses_first_relevant_result() -> None:
    ranking = ("irrelevant", "unjudged", "relevant")

    assert reciprocal_rank_at_k(ranking, {"irrelevant": 0, "relevant": 2}, cutoff=10) == (
        pytest.approx(1 / 3)
    )


def test_reciprocal_rank_is_zero_outside_cutoff() -> None:
    assert (
        reciprocal_rank_at_k(
            ("a", "b", "relevant"),
            {"relevant": 1},
            cutoff=2,
        )
        == 0.0
    )


def test_recall_uses_all_judged_relevant_documents() -> None:
    ranking = ("a", "irrelevant")
    qrels = {"a": 2, "b": 1, "irrelevant": 0}

    assert recall_at_k(ranking, qrels, cutoff=2) == pytest.approx(0.5)


def test_metric_threshold_can_require_high_relevance() -> None:
    ranking = ("partly", "highly")
    qrels = {"partly": 1, "highly": 2}

    assert reciprocal_rank_at_k(
        ranking,
        qrels,
        cutoff=2,
        relevance_threshold=2,
    ) == pytest.approx(0.5)
    assert recall_at_k(
        ranking,
        qrels,
        cutoff=2,
        relevance_threshold=2,
    ) == pytest.approx(1.0)


def test_aggregate_metrics_are_macro_averages_in_query_order() -> None:
    metrics = evaluate_rankings(
        rankings={"q002": ("b",), "q001": ("x", "a")},
        qrels={"q001": {"a": 2}, "q002": {"b": 2}},
        cutoff=10,
    )

    assert [item.query_id for item in metrics.per_query] == ["q001", "q002"]
    assert metrics.query_count == 2
    assert metrics.mrr == pytest.approx(0.75)
    assert metrics.recall == pytest.approx(1.0)
    assert metrics.ndcg == pytest.approx((1.0 / math.log2(3.0) + 1.0) / 2.0)


def test_aggregate_rejects_missing_query_rankings() -> None:
    with pytest.raises(ValueError, match="same query IDs"):
        evaluate_rankings({"q001": ("a",)}, {"q002": {"a": 2}})


def test_aggregate_rejects_query_without_relevant_judgement() -> None:
    with pytest.raises(ValueError, match="no relevant judgements"):
        evaluate_rankings({"q001": ("a",)}, {"q001": {"a": 0}})


def test_metrics_reject_duplicate_ranked_document_ids() -> None:
    with pytest.raises(ValueError, match="duplicate document IDs"):
        ndcg_at_k(("a", "a"), {"a": 2})


@pytest.mark.parametrize("cutoff", [0, 101])
def test_metrics_reject_out_of_range_cutoffs(cutoff: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 100"):
        recall_at_k(("a",), {"a": 2}, cutoff=cutoff)
