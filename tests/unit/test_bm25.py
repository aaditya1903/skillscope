"""Hand-calculated and edge-case coverage for deterministic BM25."""

import math
from dataclasses import replace
from uuid import UUID

import pytest

from skillscope.db.enums import ValidationStatus
from skillscope.retrieval.bm25 import BM25Index
from skillscope.retrieval.config import BM25BaselineConfig
from skillscope.retrieval.corpus import (
    CorpusDocument,
    FrozenCorpus,
    LexicalFields,
    StaleCorpusError,
)
from skillscope.retrieval.filters import RetrievalFilters
from skillscope.retrieval.text import tokenize

SNAPSHOT_SHA256 = "a" * 64


def _config() -> BM25BaselineConfig:
    return BM25BaselineConfig(
        k1=1.5,
        b=0.75,
        default_top_k=10,
        corpus_snapshot_path="data/manifests/test.jsonl",
        corpus_snapshot_sha256=SNAPSHOT_SHA256,
        eligible_validation_statuses=("valid", "warning"),
    )


def _document(
    number: int,
    text: str,
    *,
    repository: str = "example/catalogue",
    path: str | None = None,
) -> CorpusDocument:
    resolved_path = path or f"skills/{number}/SKILL.md"
    fields = LexicalFields(
        name_text=text,
        description_text="",
        metadata_text="",
        heading_text="",
        body_text="",
    )
    return CorpusDocument(
        document_id=f"github:{number}:{resolved_path}",
        skill_id=UUID(int=number),
        repository_id=number,
        repository_full_name=repository,
        path=resolved_path,
        name=f"skill-{number}",
        safe_snippet="Synthetic test document.",
        validation_status=ValidationStatus.VALID,
        content_sha256=f"{number % 10}" * 64,
        fields=fields,
        tokens=tokenize(fields.combined_text),
    )


def _index(*documents: CorpusDocument) -> BM25Index:
    return BM25Index(
        FrozenCorpus(
            snapshot_path="data/manifests/test.jsonl",
            snapshot_sha256=SNAPSHOT_SHA256,
            documents=documents,
        ),
        _config(),
    )


def test_idf_matches_the_hand_calculated_formula() -> None:
    index = _index(_document(1, "alpha beta beta"), _document(2, "alpha gamma"))

    expected_alpha = math.log(1 + (2 - 2 + 0.5) / (2 + 0.5))
    expected_beta = math.log(1 + (2 - 1 + 0.5) / (1 + 0.5))

    assert index.inverse_document_frequency("alpha") == pytest.approx(expected_alpha)
    assert index.inverse_document_frequency("beta") == pytest.approx(expected_beta)


def test_score_matches_an_independent_reference_calculation() -> None:
    index = _index(_document(1, "alpha beta beta"), _document(2, "alpha gamma"))

    result = index.search("beta")[0]
    expected_idf = math.log(1 + (2 - 1 + 0.5) / (1 + 0.5))
    average_length = (3 + 2) / 2
    denominator = 2 + 1.5 * (1 - 0.75 + 0.75 * 3 / average_length)
    expected_score = expected_idf * (2 * (1.5 + 1)) / denominator

    assert result.document.document_id.startswith("github:1:")
    assert result.score == pytest.approx(expected_score)
    assert result.matched_terms == ("beta",)
    assert result.term_scores[0].term_frequency == 2


def test_length_normalization_ranks_the_shorter_matching_document_first() -> None:
    index = _index(_document(1, "alpha filler filler"), _document(2, "alpha"))

    results = index.search("alpha")

    assert [result.document.repository_id for result in results] == [2, 1]


def test_empty_and_unseen_queries_return_no_results() -> None:
    index = _index(_document(1, "alpha beta"))

    assert index.search("") == ()
    assert index.search("   **  ") == ()
    assert index.search("unseen") == ()


def test_repeated_query_terms_have_binary_weight() -> None:
    index = _index(_document(1, "alpha alpha"), _document(2, "alpha"))

    single = index.search("alpha")
    repeated = index.search("alpha alpha alpha")

    assert [result.score for result in repeated] == pytest.approx(
        [result.score for result in single]
    )


def test_duplicate_documents_use_deterministic_repository_and_path_ties() -> None:
    index = _index(
        _document(2, "same tokens", repository="zeta/repo"),
        _document(1, "same tokens", repository="alpha/repo"),
    )

    results = index.search("same")

    assert [result.document.repository_full_name for result in results] == [
        "alpha/repo",
        "zeta/repo",
    ]


def test_top_k_is_bounded_and_applied_after_ranking() -> None:
    index = _index(_document(1, "alpha"), _document(2, "alpha"))

    assert len(index.search("alpha", top_k=1)) == 1
    with pytest.raises(ValueError, match="between 1 and 100"):
        index.search("alpha", top_k=0)


def test_filters_are_applied_before_bm25_candidate_selection() -> None:
    with_scripts = replace(_document(1, "alpha"), has_scripts=True)
    without_scripts = _document(2, "alpha")
    index = _index(with_scripts, without_scripts)

    results = index.search("alpha", filters=RetrievalFilters(has_scripts=True))

    assert [result.document.skill_id for result in results] == [with_scripts.skill_id]


def test_unicode_and_technical_query_tokens_match() -> None:
    index = _index(_document(1, "C++ CI/CD naïve SKILL.md"))

    result = index.search("Ｃ＋＋ ci/cd naïve skill.md")[0]  # noqa: RUF001

    assert result.matched_terms == ("c++", "ci/cd", "naïve", "skill.md")


def test_index_rejects_a_different_snapshot_hash() -> None:
    index = _index(_document(1, "alpha"))

    with pytest.raises(StaleCorpusError, match="different corpus"):
        index.assert_snapshot_hash("b" * 64)


def test_index_constructor_rejects_config_corpus_mismatch() -> None:
    corpus = FrozenCorpus(
        snapshot_path="data/manifests/test.jsonl",
        snapshot_sha256="b" * 64,
        documents=(_document(1, "alpha"),),
    )

    with pytest.raises(StaleCorpusError, match="configuration"):
        BM25Index(corpus, _config())
