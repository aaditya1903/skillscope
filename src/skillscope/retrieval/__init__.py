"""Deterministic lexical, dense, and hybrid retrieval primitives."""

from skillscope.retrieval.bm25 import BM25Index, BM25Result, BM25TermScore
from skillscope.retrieval.config import (
    BM25BaselineConfig,
    DenseHybridConfig,
    load_bm25_config,
    load_dense_hybrid_config,
)
from skillscope.retrieval.corpus import (
    CorpusDocument,
    CorpusIntegrityError,
    FrozenCorpus,
    LexicalFields,
    StaleCorpusError,
    load_frozen_corpus,
)
from skillscope.retrieval.dense import DenseResult, DenseRetriever, EmbeddingCoverageError
from skillscope.retrieval.embeddings import (
    EmbeddingContractError,
    EmbeddingEncoder,
    EmbeddingIndexSummary,
    SentenceTransformerEncoder,
    get_sentence_transformer_encoder,
    index_frozen_corpus_embeddings,
)
from skillscope.retrieval.filters import RetrievalFilters
from skillscope.retrieval.hybrid import HybridResult, HybridRetriever, reciprocal_rank_fusion
from skillscope.retrieval.text import (
    TOKEN_PATTERN,
    TOKENIZER_VERSION,
    normalize_lexical_text,
    partition_markdown_body,
    tokenize,
)

__all__ = [
    "TOKENIZER_VERSION",
    "TOKEN_PATTERN",
    "BM25BaselineConfig",
    "BM25Index",
    "BM25Result",
    "BM25TermScore",
    "CorpusDocument",
    "CorpusIntegrityError",
    "DenseHybridConfig",
    "DenseResult",
    "DenseRetriever",
    "EmbeddingContractError",
    "EmbeddingCoverageError",
    "EmbeddingEncoder",
    "EmbeddingIndexSummary",
    "FrozenCorpus",
    "HybridResult",
    "HybridRetriever",
    "LexicalFields",
    "RetrievalFilters",
    "SentenceTransformerEncoder",
    "StaleCorpusError",
    "get_sentence_transformer_encoder",
    "index_frozen_corpus_embeddings",
    "load_bm25_config",
    "load_dense_hybrid_config",
    "load_frozen_corpus",
    "normalize_lexical_text",
    "partition_markdown_body",
    "reciprocal_rank_fusion",
    "tokenize",
]
