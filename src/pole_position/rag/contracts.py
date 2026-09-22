from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

ParsedUnitKind = Literal["preamble", "article", "appendix"]


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


class ParsedUnit(BaseModel):
    kind: ParsedUnitKind
    identifier: str | None = None
    title: str
    text: str
    start_pdf_page: int = Field(gt=0)
    end_pdf_page: int = Field(gt=0)


class ParsedDocument(BaseModel):
    document_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    units: list[ParsedUnit] = Field(min_length=1)
