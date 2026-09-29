import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from math import isfinite, log1p

from pole_position.rag.contracts import RetrievalChunk

TOKEN_PATTERN = re.compile(r"[^\W_]+(?:\.[^\W_]+)*")


def tokenize(text: str) -> list[str]:
    """Normalize text while keeping identifiers such as B8.2.8 intact."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return TOKEN_PATTERN.findall(normalized)


@dataclass(frozen=True)
class BM25Match:
    chunk: RetrievalChunk
    score: float


class BM25Index:
    """An in-memory inverted index over regulation chunks."""

    def __init__(
        self,
        chunks: Iterable[RetrievalChunk],
        *,
        k1: float = 1.2,
        b: float = 0.75,
    ) -> None:
        if not isfinite(k1) or k1 <= 0:
            raise ValueError("k1 must be a positive finite number")
        if not isfinite(b) or not 0 <= b <= 1:
            raise ValueError("b must be between 0 and 1")

        self.k1 = k1
        self.b = b
        self._chunks: dict[str, RetrievalChunk] = {}
        self._document_lengths: dict[str, int] = {}

        # term -> {chunk_id: number of occurrences in that chunk}
        self._postings: dict[str, dict[str, int]] = {}

        for chunk in chunks:
            chunk_id = chunk.chunk_id
            if chunk_id in self._chunks:
                raise ValueError(f"Duplicate chunk ID: {chunk_id}")

            self._chunks[chunk_id] = chunk

            terms = tokenize(chunk.text)
            self._document_lengths[chunk_id] = len(terms)

            for term, frequency in Counter(terms).items():
                self._postings.setdefault(term, {})[chunk_id] = frequency

        if not self._chunks:
            raise ValueError("BM25 index requires at least one chunk")

        self._document_count = len(self._chunks)
        total_length = sum(self._document_lengths.values())

        # A punctuation-only corpus has no searchable terms, but should not
        # cause division by zero if search() is called.
        self._average_document_length = (
            total_length / self._document_count if total_length else 1.0
        )

    @property
    def chunk_count(self) -> int:
        return self._document_count

    def search(self, query: str, *, top_k: int = 5) -> list[BM25Match]:
        """Return matching chunks ordered by decreasing BM25 score."""
        if not query.strip():
            raise ValueError("Query cannot be empty")
        if top_k <= 0:
            raise ValueError("top_k must be positive")

        scores: dict[str, float] = defaultdict(float)

        # A repeated word in the question should not count as another
        # independent term. Term frequency in each chunk still matters.
        for term in set(tokenize(query)):
            postings = self._postings.get(term)
            if not postings:
                continue

            document_frequency = len(postings)
            idf = log1p(
                (self._document_count - document_frequency + 0.5)
                / (document_frequency + 0.5)
            )

            for chunk_id, term_frequency in postings.items():
                document_length = self._document_lengths[chunk_id]
                length_factor = (
                    1
                    - self.b
                    + self.b * document_length / self._average_document_length
                )
                denominator = term_frequency + self.k1 * length_factor

                scores[chunk_id] += idf * (term_frequency * (self.k1 + 1)) / denominator

        ranked_ids = sorted(
            scores,
            key=lambda chunk_id: (-scores[chunk_id], chunk_id),
        )

        return [
            BM25Match(chunk=self._chunks[chunk_id], score=scores[chunk_id])
            for chunk_id in ranked_ids[:top_k]
        ]
