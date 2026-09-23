from collections import Counter, defaultdict
from pathlib import Path

import pytest

from pole_position.corpus.manifest import load_manifest
from pole_position.rag.contracts import (
    ChunkedDocument,
    ExtractedDocument,
    PageTextSegment,
    ParsedClause,
    ParsedClauseDocument,
    ParsedDocument,
    ParsedUnit,
    RegulationSection,
    RetrievalChunk,
)
from pole_position.rag.ingestion.appendix_chunker import chunk_appendices
from pole_position.rag.ingestion.clause_chunker import chunk_clauses
from pole_position.rag.ingestion.clause_parser import parse_clauses
from pole_position.rag.ingestion.normalizer import (
    normalize_document,
    normalize_page_text,
)
from pole_position.rag.ingestion.preamble_chunker import chunk_preamble
from pole_position.rag.ingestion.structure_parser import parse_document

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_STAGES = ("extracted", "normalized", "parsed", "clauses", "chunks")
SECTIONS: tuple[RegulationSection, ...] = ("A", "B", "C", "D", "E", "F")
MAX_CHUNK_CHARACTERS = 1200
SOURCE_SHA256 = "a" * 64

# This is the explicit policy for the current, SHA-pinned 2026 corpus.
INDEXED_APPENDICES = {
    "A": {f"A{number}" for number in range(1, 9)},
    "B": {f"B{number}" for number in range(1, 5)},
    "C": {"C1", "C2", "C4", "C5", "C6"},
    "D": {"D1"},
    "E": {"E1", "E2"},
    "F": {"F1"},
}
FUTURE_APPENDICES = {"A9", "B5", "D2", "F2"}
VISUAL_APPENDICES = {"C3"}
SECTION_C_PAGES_WITHOUT_TEXT = {63, 221, 222, 224}


def collapsed(text: str) -> str:
    return " ".join(text.split())


def test_synthetic_chunks_preserve_text_size_ids_and_exact_pages() -> None:
    document_id = "fia-f1-2026-section-a-test"
    preamble_text = "PREAMBLE\nSafety and sporting fairness matter."
    appendix_text = "APPENDIX A1: DEFINITIONS\n" + "Defined terms apply. " * 8
    first_clause_page = "A1.1\nThe first page states the rule."
    second_clause_page = "The second page continues the same clause."

    parsed_document = ParsedDocument(
        document_id=document_id,
        source_sha256=SOURCE_SHA256,
        units=[
            ParsedUnit(
                kind="preamble",
                title="Preamble",
                text=preamble_text,
                start_pdf_page=1,
                end_pdf_page=1,
                page_segments=[
                    PageTextSegment(pdf_page_number=1, text=preamble_text)
                ],
            ),
            ParsedUnit(
                kind="appendix",
                identifier="A1",
                title="DEFINITIONS",
                text=appendix_text,
                start_pdf_page=4,
                end_pdf_page=4,
                page_segments=[
                    PageTextSegment(pdf_page_number=4, text=appendix_text)
                ],
            ),
        ],
    )
    clause_document = ParsedClauseDocument(
        document_id=document_id,
        source_sha256=SOURCE_SHA256,
        clauses=[
            ParsedClause(
                article_identifier="A1",
                clause_identifier="A1.1",
                text=f"{first_clause_page}\n{second_clause_page}",
                start_pdf_page=2,
                end_pdf_page=3,
                page_segments=[
                    PageTextSegment(pdf_page_number=2, text=first_clause_page),
                    PageTextSegment(pdf_page_number=3, text=second_clause_page),
                ],
            )
        ],
    )

    clause_chunks = chunk_clauses(clause_document, max_characters=55).chunks
    appendix_chunks, skipped_future, skipped_visual = chunk_appendices(
        parsed_document, "A", max_characters=55
    )
    preamble_chunks = chunk_preamble(parsed_document, "A", max_characters=55)
    chunks = [*clause_chunks, *appendix_chunks, *preamble_chunks]

    assert not skipped_future and not skipped_visual
    assert {chunk.source_kind for chunk in chunks} == {
        "clause",
        "appendix",
        "preamble",
    }
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)
    assert all(len(chunk.text) <= 55 for chunk in chunks)
    assert all(chunk.start_pdf_page == chunk.end_pdf_page for chunk in chunks)
    assert {chunk.start_pdf_page for chunk in clause_chunks} == {2, 3}
    assert {chunk.start_pdf_page for chunk in appendix_chunks} == {4}
    assert {chunk.start_pdf_page for chunk in preamble_chunks} == {1}
    assert collapsed(" ".join(chunk.text for chunk in clause_chunks)) == collapsed(
        clause_document.clauses[0].text
    )
    assert collapsed(" ".join(chunk.text for chunk in appendix_chunks)) == collapsed(
        appendix_text
    )
    assert collapsed(" ".join(chunk.text for chunk in preamble_chunks)) == collapsed(
        preamble_text
    )


@pytest.mark.parametrize("section", SECTIONS)
def test_synthetic_appendix_policy_excludes_future_and_visual_material(
    section: RegulationSection,
) -> None:
    identifiers = sorted(
        INDEXED_APPENDICES[section]
        | {identifier for identifier in FUTURE_APPENDICES if identifier[0] == section}
        | {identifier for identifier in VISUAL_APPENDICES if identifier[0] == section}
    )
    units = []
    for page_number, identifier in enumerate(identifiers, start=1):
        text = f"APPENDIX {identifier}: TEST\nText for {identifier}."
        units.append(
            ParsedUnit(
                kind="appendix",
                identifier=identifier,
                title="TEST",
                text=text,
                start_pdf_page=page_number,
                end_pdf_page=page_number,
                page_segments=[
                    PageTextSegment(pdf_page_number=page_number, text=text)
                ],
            )
        )

    document = ParsedDocument(
        document_id=f"fia-f1-2026-section-{section.lower()}-test",
        source_sha256=SOURCE_SHA256,
        units=units,
    )
    chunks, skipped_future, skipped_visual = chunk_appendices(document, section)

    assert {chunk.appendix_identifier for chunk in chunks} == INDEXED_APPENDICES[
        section
    ]
    assert len(chunks) == len(INDEXED_APPENDICES[section])
    assert set(skipped_future) == {
        identifier for identifier in FUTURE_APPENDICES if identifier[0] == section
    }
    assert set(skipped_visual) == {
        identifier for identifier in VISUAL_APPENDICES if identifier[0] == section
    }
    assert chunk_preamble(document, section) == []


@pytest.mark.parametrize("page_number", sorted(SECTION_C_PAGES_WITHOUT_TEXT))
def test_section_c_header_only_page_does_not_create_searchable_text(
    page_number: int,
) -> None:
    raw_text = (
        "SECTION C: TECHNICAL REGULATIONS\n"
        f"C{page_number}\n"
        "2026 Formula 1 Regulations - Section C [Technical]\n"
        "©2026 Fédération Internationale de l’Automobile\n"
        "05 August 2026\n"
        "Issue 20\n"
        "0\n"
        "C\n"
    )

    assert normalize_page_text(raw_text) == ""


def test_local_corpus_artifacts_are_index_ready() -> None:
    """Audit real generated JSON locally; it is intentionally Git-ignored."""
    manifest = load_manifest(
        PROJECT_ROOT / "data/manifests/2026_f1_regulations.json"
    )
    artifact_paths = [
        PROJECT_ROOT / "artifacts" / stage / f"{document.document_id}.json"
        for document in manifest.documents
        for stage in ARTIFACT_STAGES
    ]

    if not any(path.exists() for path in artifact_paths):
        pytest.skip("Local artifacts absent; run ingestion to enable corpus audit")

    missing_paths = [str(path) for path in artifact_paths if not path.exists()]
    assert not missing_paths, f"Incomplete ingestion artifacts: {missing_paths}"
    assert {document.section for document in manifest.documents} == set(SECTIONS)

    seen_chunk_ids: set[str] = set()
    chunk_counts: Counter[str] = Counter()

    for document in manifest.documents:
        directory = PROJECT_ROOT / "artifacts"
        filename = f"{document.document_id}.json"
        extracted = ExtractedDocument.model_validate_json(
            (directory / "extracted" / filename).read_text(encoding="utf-8")
        )
        normalized = ExtractedDocument.model_validate_json(
            (directory / "normalized" / filename).read_text(encoding="utf-8")
        )
        parsed = ParsedDocument.model_validate_json(
            (directory / "parsed" / filename).read_text(encoding="utf-8")
        )
        clauses = ParsedClauseDocument.model_validate_json(
            (directory / "clauses" / filename).read_text(encoding="utf-8")
        )
        chunked = ChunkedDocument.model_validate_json(
            (directory / "chunks" / filename).read_text(encoding="utf-8")
        )

        for stage in (extracted, normalized, parsed, clauses, chunked):
            assert stage.document_id == document.document_id
            assert stage.source_sha256 == document.sha256
        assert len(extracted.pages) == len(normalized.pages) == document.page_count

        # Detect stale JSON from a previous version of the pipeline.
        assert normalize_document(extracted) == normalized
        assert parse_document(normalized) == parsed
        assert parse_clauses(normalized) == clauses
        clause_chunks = chunk_clauses(clauses).chunks
        appendix_chunks, skipped_future, skipped_visual = chunk_appendices(
            parsed, document.section
        )
        preamble_chunks = chunk_preamble(parsed, document.section)
        assert chunked.chunks == [
            *clause_chunks,
            *appendix_chunks,
            *preamble_chunks,
        ]

        pages = {page.pdf_page_number: page.text for page in normalized.pages}
        blank_pages = {number for number, text in pages.items() if not text.strip()}
        if document.section == "C":
            assert blank_pages == SECTION_C_PAGES_WITHOUT_TEXT
        else:
            assert not blank_pages

        chunks_by_clause_page: dict[tuple[str | None, int], list[RetrievalChunk]] = (
            defaultdict(list)
        )
        chunks_by_appendix_page: dict[tuple[str | None, int], list[RetrievalChunk]] = (
            defaultdict(list)
        )
        chunks_by_preamble_page: dict[int, list[RetrievalChunk]] = defaultdict(list)

        for chunk in chunked.chunks:
            assert chunk.chunk_id not in seen_chunk_ids
            seen_chunk_ids.add(chunk.chunk_id)
            chunk_counts[chunk.source_kind] += 1
            assert chunk.section == document.section
            assert 1 <= chunk.start_pdf_page == chunk.end_pdf_page <= document.page_count
            assert chunk.start_pdf_page not in blank_pages
            assert len(chunk.text) <= MAX_CHUNK_CHARACTERS

            if chunk.source_kind == "clause":
                chunks_by_clause_page[
                    (chunk.clause_identifier, chunk.start_pdf_page)
                ].append(chunk)
            elif chunk.source_kind == "appendix":
                chunks_by_appendix_page[
                    (chunk.appendix_identifier, chunk.start_pdf_page)
                ].append(chunk)
            else:
                chunks_by_preamble_page[chunk.start_pdf_page].append(chunk)

        for clause in clauses.clauses:
            assert collapsed(clause.text) == collapsed(
                " ".join(segment.text for segment in clause.page_segments)
            )
            for segment in clause.page_segments:
                assert segment.text in pages[segment.pdf_page_number]
                pieces = chunks_by_clause_page[
                    (clause.clause_identifier, segment.pdf_page_number)
                ]
                assert pieces, (document.section, clause.clause_identifier)
                assert collapsed(" ".join(piece.text for piece in pieces)) == (
                    collapsed(segment.text)
                )

        appendix_units = [unit for unit in parsed.units if unit.kind == "appendix"]
        assert {unit.identifier for unit in appendix_units} == (
            INDEXED_APPENDICES[document.section]
            | {identifier for identifier in FUTURE_APPENDICES if identifier[0] == document.section}
            | {identifier for identifier in VISUAL_APPENDICES if identifier[0] == document.section}
        )
        assert set(skipped_future) == {
            identifier for identifier in FUTURE_APPENDICES if identifier[0] == document.section
        }
        assert set(skipped_visual) == {
            identifier for identifier in VISUAL_APPENDICES if identifier[0] == document.section
        }
        assert {chunk.appendix_identifier for chunk in appendix_chunks} == (
            INDEXED_APPENDICES[document.section]
        )

        unit_segments_by_page: dict[int, list[str]] = defaultdict(list)
        for unit in parsed.units:
            for segment in unit.page_segments:
                assert segment.text in pages[segment.pdf_page_number]
                unit_segments_by_page[segment.pdf_page_number].append(segment.text)

                if unit.kind == "appendix" and unit.identifier in INDEXED_APPENDICES[
                    document.section
                ]:
                    pieces = chunks_by_appendix_page[
                        (unit.identifier, segment.pdf_page_number)
                    ]
                    assert pieces, (document.section, unit.identifier)
                    assert collapsed(" ".join(piece.text for piece in pieces)) == (
                        collapsed(segment.text)
                    )
                elif unit.kind == "preamble":
                    pieces = chunks_by_preamble_page[segment.pdf_page_number]
                    assert pieces, document.section
                    assert collapsed(" ".join(piece.text for piece in pieces)) == (
                        collapsed(segment.text)
                    )

        first_content_page = min(unit_segments_by_page)
        for page_number, text in pages.items():
            if page_number < first_content_page or not text.strip():
                continue
            assert collapsed(text) == collapsed(
                " ".join(unit_segments_by_page[page_number])
            ), (document.section, page_number)

        expected_preambles = 1 if document.section == "A" else 0
        assert sum(unit.kind == "preamble" for unit in parsed.units) == (
            expected_preambles
        )
        assert len(preamble_chunks) == expected_preambles
        if document.section == "C":
            appendix_c3 = next(
                unit for unit in appendix_units if unit.identifier == "C3"
            )
            assert (appendix_c3.start_pdf_page, appendix_c3.end_pdf_page) == (
                220,
                224,
            )

    assert chunk_counts == Counter({"clause": 2411, "appendix": 422, "preamble": 1})
    assert len(seen_chunk_ids) == sum(chunk_counts.values())
