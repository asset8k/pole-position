from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pole_position.corpus.schemas import RegulationSection


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=4_000)


class Citation(BaseModel):
    source_id: str = Field(pattern=r"^S[1-9]\d*$")
    chunk_id: str
    document_id: str
    document_title: str
    section: RegulationSection
    source_kind: Literal["clause", "appendix", "preamble"]
    article_identifier: str | None = None
    clause_identifier: str | None = None
    appendix_identifier: str | None = None
    start_pdf_page: int = Field(gt=0)
    end_pdf_page: int = Field(gt=0)
    snippet: str


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    conversation_id: int | None = None
