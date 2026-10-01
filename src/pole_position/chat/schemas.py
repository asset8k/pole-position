from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pole_position.corpus.schemas import RegulationSection


class ChatHistoryMessage(BaseModel):
    """Previous guest messages used to understand follow-up questions."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8_000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    message: str = Field(min_length=1, max_length=4_000)
    conversation_id: int | None = Field(default=None, gt=0)

    # Guests send recent history; registered users use database history.
    history: list[ChatHistoryMessage] = Field(
        default_factory=list,
        max_length=10,
    )


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
    conversation_id: int | None = Field(default=None, gt=0)


class MessageResponse(BaseModel):
    """A message loaded from a saved conversation."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    role: Literal["user", "assistant"]
    content: str
    citations: list[Citation] = Field(default_factory=list)
    created_at: datetime


class ConversationResponse(BaseModel):
    """Conversation metadata used when listing saved conversations."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationDetailResponse(ConversationResponse):
    """A saved conversation together with its ordered messages."""

    messages: list[MessageResponse] = Field(default_factory=list)


class ConversationUpdateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    title: str = Field(min_length=1, max_length=160)
