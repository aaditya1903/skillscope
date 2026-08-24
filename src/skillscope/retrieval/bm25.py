"""Transparent Okapi BM25 indexing, ranking, and score explanations."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass

from skillscope.retrieval.config import BM25BaselineConfig
from skillscope.retrieval.corpus import CorpusDocument, FrozenCorpus, StaleCorpusError
from skillscope.retrieval.text import tokenize


@dataclass(frozen=True, slots=True)
class BM25TermScore:
    """One matched query term's contribution to a document score."""

    term: str
    term_frequency: int
    document_frequency: int
    inverse_document_frequency: float
    score: float


@dataclass(frozen=True, slots=True)
class BM25Result:
    """One deterministically ranked document and its explanation."""

    document: CorpusDocument
    score: float
    matched_terms: tuple[str, ...]
    term_scores: tuple[BM25TermScore, ...]


class BM25Index:
    """An in-memory BM25 index tied to one frozen corpus SHA-256."""

    def __init__(self, corpus: FrozenCorpus, config: BM25BaselineConfig) -> None:
        if corpus.snapshot_sha256 != config.corpus_snapshot_sha256:
            raise StaleCorpusError("BM25 index corpus does not match its baseline configuration")

        self.config = config
        self.snapshot_sha256 = corpus.snapshot_sha256
        self.documents = corpus.documents
        self.document_lengths = tuple(len(document.tokens) for document in self.documents)
        self.average_document_length = (
            sum(self.document_lengths) / len(self.document_lengths)
            if self.document_lengths
            else 0.0
        )

        postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for document_index, document in enumerate(self.documents):
            frequencies = Counter(document.tokens)
            for term, frequency in frequencies.items():
                postings[term].append((document_index, frequency))
        self._postings = {term: tuple(term_postings) for term, term_postings in postings.items()}

    @property
    def document_count(self) -> int:
        return len(self.documents)

    def inverse_document_frequency(self, term: str) -> float:
        """Return Robertson-Sparck Jones IDF with the positive BM25 variant."""

        document_frequency = len(self._postings.get(term, ()))
        if document_frequency == 0 or self.document_count == 0:
            return 0.0
        return math.log(
            1.0 + (self.document_count - document_frequency + 0.5) / (document_frequency + 0.5)
        )

    def assert_snapshot_hash(self, snapshot_sha256: str) -> None:
        """Reject use of this index with different corpus bytes."""

        if snapshot_sha256 != self.snapshot_sha256:
            raise StaleCorpusError("BM25 index was built from a different corpus snapshot")

    def search(self, query: str, *, top_k: int | None = None) -> tuple[BM25Result, ...]:
        """Rank documents for one query using binary repeated-term semantics."""

        result_limit = top_k if top_k is not None else self.config.default_top_k
        if not 1 <= result_limit <= 100:
            raise ValueError("top_k must be between 1 and 100")

        # Dict insertion order retains the first normalized occurrence. Repeated
        # query terms therefore have binary weight and cannot inflate a score.
        query_terms = tuple(dict.fromkeys(tokenize(query)))
        if not query_terms:
            return ()

        scores: dict[int, float] = defaultdict(float)
        components: dict[int, list[BM25TermScore]] = defaultdict(list)
        for term in query_terms:
            term_postings = self._postings.get(term, ())
            if not term_postings:
                continue
            document_frequency = len(term_postings)
            inverse_document_frequency = self.inverse_document_frequency(term)
            for document_index, term_frequency in term_postings:
                component = self._term_score(
                    term_frequency=term_frequency,
                    document_length=self.document_lengths[document_index],
                    inverse_document_frequency=inverse_document_frequency,
                )
                scores[document_index] += component
                components[document_index].append(
                    BM25TermScore(
                        term=term,
                        term_frequency=term_frequency,
                        document_frequency=document_frequency,
                        inverse_document_frequency=inverse_document_frequency,
                        score=component,
                    )
                )

        ranked = [
            BM25Result(
                document=self.documents[document_index],
                score=score,
                matched_terms=tuple(item.term for item in components[document_index]),
                term_scores=tuple(components[document_index]),
            )
            for document_index, score in scores.items()
            if score > 0.0
        ]
        ranked.sort(
            key=lambda result: (
                -result.score,
                result.document.repository_full_name.casefold(),
                result.document.path.casefold(),
                result.document.document_id,
            )
        )
        return tuple(ranked[:result_limit])

    def _term_score(
        self,
        *,
        term_frequency: int,
        document_length: int,
        inverse_document_frequency: float,
    ) -> float:
        if term_frequency <= 0 or self.average_document_length <= 0.0:
            return 0.0
        length_normalization = (
            1.0 - self.config.b + self.config.b * (document_length / self.average_document_length)
        )
        numerator = term_frequency * (self.config.k1 + 1.0)
        denominator = term_frequency + self.config.k1 * length_normalization
        return inverse_document_frequency * numerator / denominator
