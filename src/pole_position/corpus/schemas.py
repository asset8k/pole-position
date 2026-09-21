from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

RegulationSection = Literal["A", "B", "C", "D", "E", "F"]


class RegulationDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1)
    section: RegulationSection
    title: str = Field(min_length=1)
    season: int = Field(ge=1950)
    issue_number: int = Field(gt=0)
    published_date: date
    wmsc_approval_date: date
    source_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    page_count: int = Field(gt=0)
    is_active: bool


class CorpusManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_version: Literal[1] = 1
    documents: list[RegulationDocument] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_documents(self) -> Self:
        document_ids = [document.document_id for document in self.documents]

        if len(document_ids) != len(set(document_ids)):
            raise ValueError("Document IDs must be unique")

        active_sections = [
            document.section for document in self.documents if document.is_active
        ]

        duplicate_active_sections = {
            section for section in active_sections if active_sections.count(section) > 1
        }

        if duplicate_active_sections:
            sections = ", ".join(sorted(duplicate_active_sections))
            raise ValueError(
                f"Only one active document is allowed per section: {sections}"
            )

        return self
