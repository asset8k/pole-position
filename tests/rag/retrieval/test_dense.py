from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from openai import OpenAI
from qdrant_client import QdrantClient, models

from pole_position.corpus.schemas import RegulationDocument
from pole_position.rag.contracts import ChunkedDocument, RetrievalChunk
from pole_position.rag.indexing.qdrant_store import upsert_chunked_document
from pole_position.rag.retrieval.dense import retrieve_dense


def make_document(section: str, title: str) -> RegulationDocument:
    return RegulationDocument(
        document_id=f"fia-f1-2026-section-{section.lower()}-issue-01",
        section=section,  # type: ignore[arg-type]
        title=title,
        season=2026,
        issue_number=1,
        published_date=date(2026, 1, 1),
        wmsc_approval_date=date(2025, 12, 1),
        source_path=f"regulations/section_{section.lower()}.pdf",
        sha256="a" * 64,
        page_count=10,
        is_active=True,
    )


def make_chunk(document: RegulationDocument, clause: str) -> RetrievalChunk:
    return RetrievalChunk(
        chunk_id=f"{document.document_id}:{clause}:0",
        document_id=document.document_id,
        source_sha256=document.sha256,
        section=document.section,
        source_kind="clause",
        article_identifier=clause.split(".")[0],
        clause_identifier=clause,
        chunk_index=0,
        text=f"Text of {clause}.",
        start_pdf_page=5,
        end_pdf_page=5,
    )


def test_retrieve_dense_returns_ranked_chunk_and_citation_metadata() -> None:
    client = QdrantClient(":memory:")
    document = make_document("B", "Sporting Regulations")
    chunk = make_chunk(document, "B8.2.8")
    upsert_chunked_document(
        client,
        "regulations",
        ChunkedDocument(
            document_id=document.document_id,
            source_sha256=document.sha256,
            chunks=[chunk],
        ),
        [[1.0, 0.0]],
        document,
    )
    openai_client = Mock(spec=OpenAI)

    with patch(
        "pole_position.rag.retrieval.dense.embed_texts",
        return_value=[[1.0, 0.0]],
    ) as embed_mock:
        hits = retrieve_dense(
            "  power unit allocation?  ",
            openai_client=openai_client,
            qdrant_client=client,
            collection_name="regulations",
            top_k=5,
        )

    embed_mock.assert_called_once_with(openai_client, ["power unit allocation?"])
    assert len(hits) == 1
    assert hits[0].chunk == chunk
    assert hits[0].chunk.start_pdf_page == 5
    assert hits[0].document_title == document.title
    assert hits[0].score == pytest.approx(1.0)


def test_retrieve_dense_applies_section_filter() -> None:
    client = QdrantClient(":memory:")
    for section, clause, vector in (
        ("A", "A1.1.1", [1.0, 0.0]),
        ("B", "B8.2.8", [0.0, 1.0]),
    ):
        document = make_document(section, f"Section {section}")
        chunk = make_chunk(document, clause)
        upsert_chunked_document(
            client,
            "regulations",
            ChunkedDocument(
                document_id=document.document_id,
                source_sha256=document.sha256,
                chunks=[chunk],
            ),
            [vector],
            document,
        )

    with patch(
        "pole_position.rag.retrieval.dense.embed_texts",
        return_value=[[1.0, 0.0]],
    ):
        hits = retrieve_dense(
            "question",
            openai_client=Mock(spec=OpenAI),
            qdrant_client=client,
            collection_name="regulations",
            top_k=1,
            section="B",
        )

    assert len(hits) == 1
    assert hits[0].chunk.section == "B"
    assert hits[0].chunk.clause_identifier == "B8.2.8"


@pytest.mark.parametrize(
    ("question", "collection_name", "top_k", "message"),
    [
        ("  ", "regulations", 5, "Question cannot be empty"),
        ("question", "regulations", 0, "top_k must be positive"),
        ("question", "  ", 5, "Collection name cannot be empty"),
    ],
)
def test_retrieve_dense_rejects_invalid_inputs(
    question: str,
    collection_name: str,
    top_k: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        retrieve_dense(
            question,
            openai_client=Mock(spec=OpenAI),
            qdrant_client=Mock(spec=QdrantClient),
            collection_name=collection_name,
            top_k=top_k,
        )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (None, "has no payload"),
        ({"document_title": ""}, "has no document title"),
    ],
)
def test_retrieve_dense_rejects_missing_payload_metadata(
    payload: dict[str, str] | None,
    message: str,
) -> None:
    client = Mock(spec=QdrantClient)
    client.query_points.return_value = SimpleNamespace(
        points=[SimpleNamespace(id="point-id", payload=payload, score=0.9)]
    )

    with patch(
        "pole_position.rag.retrieval.dense.embed_texts",
        return_value=[[1.0, 0.0]],
    ), pytest.raises(RuntimeError, match=message):
        retrieve_dense(
            "question",
            openai_client=Mock(spec=OpenAI),
            qdrant_client=client,
            collection_name="regulations",
        )


def test_retrieve_dense_passes_named_vector_and_filter_to_qdrant() -> None:
    client = Mock(spec=QdrantClient)
    client.query_points.return_value = SimpleNamespace(points=[])

    with patch(
        "pole_position.rag.retrieval.dense.embed_texts",
        return_value=[[1.0, 0.0]],
    ):
        hits = retrieve_dense(
            "question",
            openai_client=Mock(spec=OpenAI),
            qdrant_client=client,
            collection_name="regulations",
            top_k=3,
            section="B",
        )

    assert hits == []
    kwargs = client.query_points.call_args.kwargs
    assert kwargs["query"] == [1.0, 0.0]
    assert kwargs["using"] == "dense"
    assert kwargs["limit"] == 3
    assert kwargs["with_payload"] is True
    assert kwargs["with_vectors"] is False
    assert kwargs["query_filter"] == models.Filter(
        must=[
            models.FieldCondition(
                key="section",
                match=models.MatchValue(value="B"),
            )
        ]
    )
