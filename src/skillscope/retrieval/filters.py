"""Shared pre-retrieval filters for lexical, dense, and hybrid ranking."""

from __future__ import annotations

from dataclasses import dataclass

from skillscope.db.enums import LicenseStatus, ValidationStatus
from skillscope.retrieval.corpus import CorpusDocument, FrozenCorpus


@dataclass(frozen=True, slots=True)
class RetrievalFilters:
    """Optional filters applied before each retriever selects candidates."""

    license_statuses: frozenset[LicenseStatus] | None = None
    validation_statuses: frozenset[ValidationStatus] | None = None
    has_scripts: bool | None = None

    def allows(self, document: CorpusDocument) -> bool:
        """Return whether one frozen document satisfies every active filter."""

        if (
            self.license_statuses is not None
            and document.license_status not in self.license_statuses
        ):
            return False
        if (
            self.validation_statuses is not None
            and document.validation_status not in self.validation_statuses
        ):
            return False
        return self.has_scripts is None or document.has_scripts is self.has_scripts

    def document_ids(self, corpus: FrozenCorpus) -> frozenset[str]:
        """Return stable IDs eligible for scoring in the frozen corpus."""

        return frozenset(
            document.document_id for document in corpus.documents if self.allows(document)
        )
