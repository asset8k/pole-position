from math import log

import pytest

from pole_position.rag.contracts import RetrievalChunk
from pole_position.rag.indexing.bm25_index import BM25Index, tokenize

DOCUMENT_ID = "fia-f1-2026-section-b-issue-08"


def make_chunk(chunk_id: str, text: str) -> RetrievalChunk:
    return RetrievalChunk(
        chunk_id=chunk_id,
        document_id=DOCUMENT_ID,
        source_sha256="a" * 64,
        section="B",
        source_kind="clause",
        article_identifier="B8",
        clause_identifier="B8.2.8",
        chunk_index=0,
        text=text,
        start_pdf_page=67,
        end_pdf_page=67,
    )


def test_tokenize_preserves_clause_identifiers_and_normalizes_pdf_ligatures() -> None:
    assert tokenize("B8.2.8: The \ufb01rst POWER-unit") == [
        "b8.2.8",
        "the",
        "first",
        "power",
        "unit",
    ]


def test_search_returns_only_matching_chunks_and_respects_top_k() -> None:
    index = BM25Index(
        [
            make_chunk("a", "B8.2.8 Power Unit penalty"),
            make_chunk("b", "B8.2.3 Power Unit allocation"),
            make_chunk("c", "Factory shutdown period"),
        ]
    )

    assert index.chunk_count == 3
    assert [match.chunk.chunk_id for match in index.search("B8.2.8")] == ["a"]
    assert [match.chunk.chunk_id for match in index.search("power", top_k=1)] == [
        "a"
    ]
    assert index.search("unmatched") == []
    assert index.search("?!") == []


def test_rare_query_term_outweighs_common_term() -> None:
    index = BM25Index(
        [
            make_chunk("common", "power power power power"),
            make_chunk("rare", "power transponder"),
            make_chunk("other", "power"),
        ]
    )

    matches = index.search("power transponder")

    assert matches[0].chunk.chunk_id == "rare"
    assert matches[0].score > matches[1].score


def test_repeated_term_in_chunk_increases_score() -> None:
    index = BM25Index(
        [
            make_chunk("repeated", "power power unit"),
            make_chunk("single", "power unit unit"),
        ]
    )

    matches = index.search("power")

    assert [match.chunk.chunk_id for match in matches] == ["repeated", "single"]
    assert matches[0].score > matches[1].score


def test_shorter_chunk_scores_higher_when_term_frequency_is_equal() -> None:
    index = BM25Index(
        [
            make_chunk("short", "power unit"),
            make_chunk("long", "power unit unrelated unrelated unrelated"),
        ]
    )

    matches = index.search("power")

    assert [match.chunk.chunk_id for match in matches] == ["short", "long"]
    assert matches[0].score > matches[1].score


def test_search_uses_positive_bm25_idf_and_deduplicates_query_terms() -> None:
    index = BM25Index(
        [make_chunk("power", "power"), make_chunk("other", "shutdown")]
    )

    match = index.search("power")[0]

    assert match.score == pytest.approx(log(2))
    assert index.search("power power")[0].score == pytest.approx(match.score)


def test_equal_scores_are_ordered_by_chunk_id() -> None:
    index = BM25Index(
        [make_chunk("z", "power"), make_chunk("a", "power")]
    )

    assert [match.chunk.chunk_id for match in index.search("power")] == ["a", "z"]


def test_punctuation_only_corpus_has_no_matches() -> None:
    index = BM25Index([make_chunk("punctuation", "...")])

    assert index.search("power") == []


def test_index_rejects_empty_corpus_and_duplicate_chunk_ids() -> None:
    with pytest.raises(ValueError, match="at least one chunk"):
        BM25Index([])

    with pytest.raises(ValueError, match="Duplicate chunk ID: same"):
        BM25Index(
            iter([make_chunk("same", "power"), make_chunk("same", "unit")])
        )


@pytest.mark.parametrize("k1", [0, -1, float("nan"), float("inf")])
def test_index_rejects_invalid_k1(k1: float) -> None:
    with pytest.raises(ValueError, match="k1 must be a positive finite number"):
        BM25Index([make_chunk("a", "power")], k1=k1)


@pytest.mark.parametrize("b", [-0.1, 1.1, float("nan"), float("inf")])
def test_index_rejects_invalid_b(b: float) -> None:
    with pytest.raises(ValueError, match="b must be between 0 and 1"):
        BM25Index([make_chunk("a", "power")], b=b)


@pytest.mark.parametrize(
    ("query", "top_k", "message"),
    [
        ("  ", 5, "Query cannot be empty"),
        ("power", 0, "top_k must be positive"),
    ],
)
def test_search_rejects_invalid_inputs(
    query: str, top_k: int, message: str
) -> None:
    index = BM25Index([make_chunk("a", "power")])

    with pytest.raises(ValueError, match=message):
        index.search(query, top_k=top_k)
