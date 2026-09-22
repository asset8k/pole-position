from typing import Self

from pydantic import BaseModel, Field, model_validator


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
