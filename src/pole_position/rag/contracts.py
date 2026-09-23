from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

ParsedUnitKind = Literal["preamble", "article", "appendix"]
RegulationSection = Literal["A", "B", "C", "D", "E", "F"]


class ExtractedPage(BaseModel):
    pdf_page_number: int = Field(gt=0)
    text: str


class ExtractedDocument(BaseModel):
    document_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    pages: list[ExtractedPage] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_page_numbers(self) -> Self:
        page_numbers = [page.pdf_page_number for page in self.pages]
        expected_page_numbers = list(range(1, len(self.pages) + 1))

        if page_numbers != expected_page_numbers:
            raise ValueError(
                "Extracted pages must be ordered and numbered consecutively from 1"
            )

        return self


class PageTextSegment(BaseModel):
    pdf_page_number: int = Field(gt=0)
    text: str = Field(min_length=1)


class ParsedUnit(BaseModel):
    kind: ParsedUnitKind
    identifier: str | None = None
    title: str
    text: str
    start_pdf_page: int = Field(gt=0)
    end_pdf_page: int = Field(gt=0)
    page_segments: list[PageTextSegment] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_page_segments(self) -> Self:
        if self.end_pdf_page < self.start_pdf_page:
            raise ValueError("Unit end PDF page cannot precede its start PDF page")

        page_numbers = [segment.pdf_page_number for segment in self.page_segments]

        if page_numbers != sorted(set(page_numbers)):
            raise ValueError("Unit page segments must be ordered and unique")

        if any(
            not self.start_pdf_page <= number <= self.end_pdf_page
            for number in page_numbers
        ):
            raise ValueError("Unit page segment is outside the unit page range")

        return self


class ParsedDocument(BaseModel):
    document_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    units: list[ParsedUnit] = Field(min_length=1)


class ParsedClause(BaseModel):
    article_identifier: str = Field(pattern=r"^[A-F]\d+$")
    clause_identifier: str = Field(pattern=r"^[A-F]\d+(?:\.\d+)+$")
    title: str | None = None
    text: str = Field(min_length=1)
    start_pdf_page: int = Field(gt=0)
    end_pdf_page: int = Field(gt=0)
    page_segments: list[PageTextSegment] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_article_relationship_and_page_range(
        self: "ParsedClause",
    ) -> "ParsedClause":
        if not self.clause_identifier.startswith(f"{self.article_identifier}."):
            raise ValueError("Clause identifier must belong to its parent Article")

        if self.end_pdf_page < self.start_pdf_page:
            raise ValueError("Clause end PDF page cannot precede its start PDF page")

        page_numbers = [segment.pdf_page_number for segment in self.page_segments]

        if page_numbers != sorted(set(page_numbers)):
            raise ValueError("Clause page segments must be ordered and unique")

        if (
            page_numbers[0] != self.start_pdf_page
            or page_numbers[-1] != self.end_pdf_page
        ):
            raise ValueError("Clause page segments must match its page range")

        return self


class ParsedClauseDocument(BaseModel):
    document_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    clauses: list[ParsedClause] = Field(min_length=1)


class RetrievalChunk(BaseModel):
    chunk_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    section: RegulationSection

    source_kind: Literal["clause", "appendix"]

    article_identifier: str | None = Field(default=None, pattern=r"^[A-F]\d+$")
    clause_identifier: str | None = Field(default=None, pattern=r"^[A-F]\d+(?:\.\d+)+$")
    clause_title: str | None = None

    appendix_identifier: str | None = Field(default=None, pattern=r"^[A-F]\d+$")
    appendix_title: str | None = None

    chunk_index: int = Field(ge=0)
    text: str = Field(min_length=1)
    start_pdf_page: int = Field(gt=0)
    end_pdf_page: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_chunk_provenance(self) -> Self:
        if self.end_pdf_page < self.start_pdf_page:
            raise ValueError("Chunk end PDF page cannot precede its start PDF page")

        if self.source_kind == "clause":
            if self.article_identifier is None or self.clause_identifier is None:
                raise ValueError("Clause chunk requires article and clause identifiers")

            if self.appendix_identifier is not None or self.appendix_title is not None:
                raise ValueError("Clause chunk cannot contain appendix metadata")

            if not self.article_identifier.startswith(self.section):
                raise ValueError("Article identifier must belong to its Section")

            if not self.clause_identifier.startswith(f"{self.article_identifier}."):
                raise ValueError("Clause identifier must belong to its parent Article")

        else:
            if self.appendix_identifier is None:
                raise ValueError("Appendix chunk requires an appendix identifier")

            if (
                self.article_identifier is not None
                or self.clause_identifier is not None
                or self.clause_title is not None
            ):
                raise ValueError("Appendix chunk cannot contain clause metadata")

            if not self.appendix_identifier.startswith(self.section):
                raise ValueError("Appendix identifier must belong to its Section")

        return self


class ChunkedDocument(BaseModel):
    document_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    chunks: list[RetrievalChunk] = Field(min_length=1)
