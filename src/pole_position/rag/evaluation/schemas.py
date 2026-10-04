from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    model_validator,
)

from pole_position.chat.schemas import ChatHistoryMessage

type EvaluationCategory = Literal[
    "exact_lookup",
    "semantic",
    "numerical",
    "cross_document",
    "terminology",
    "unanswerable",
    "follow_up",
]

type NonEmptyText = Annotated[str, Field(min_length=1)]


class ExpectedSource(BaseModel):
    """A verified evidence unit that retrieval should find."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    document_id: str = Field(min_length=1)
    source_kind: Literal["clause", "appendix", "preamble"]

    clause_identifier: str | None = Field(
        default=None,
        pattern=r"^[A-F]\d+(?:\.\d+)+$",
    )
    appendix_identifier: str | None = Field(
        default=None,
        pattern=r"^[A-F]\d+$",
    )

    # One-based PDF pages containing the relevant evidence.
    pdf_pages: list[PositiveInt] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_source_metadata(self) -> Self:
        if self.source_kind == "clause":
            if self.clause_identifier is None:
                raise ValueError("Clause source requires a clause identifier")
            if self.appendix_identifier is not None:
                raise ValueError("Clause source cannot contain an appendix identifier")

        elif self.source_kind == "appendix":
            if self.appendix_identifier is None:
                raise ValueError("Appendix source requires an appendix identifier")
            if self.clause_identifier is not None:
                raise ValueError("Appendix source cannot contain a clause identifier")

        else:
            if (
                self.clause_identifier is not None
                or self.appendix_identifier is not None
            ):
                raise ValueError("Preamble source cannot contain identifiers")

        if len(self.pdf_pages) != len(set(self.pdf_pages)):
            raise ValueError("Expected PDF pages must be unique")

        return self


class EvaluationCase(BaseModel):
    """One question and its manually verified expectations."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    id: str = Field(min_length=1)
    category: EvaluationCategory
    question: str = Field(min_length=1, max_length=4_000)

    # Previous messages only; question above is the latest user message.
    history: list[ChatHistoryMessage] = Field(
        default_factory=list,
        max_length=10,
    )

    answerable: bool
    expected_sources: list[ExpectedSource] = Field(default_factory=list)
    expected_facts: list[NonEmptyText] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_expectations(self) -> Self:
        if self.answerable:
            if not self.expected_sources:
                raise ValueError("Answerable cases require expected sources")
            if not self.expected_facts:
                raise ValueError("Answerable cases require expected facts")
        elif self.expected_sources or self.expected_facts:
            raise ValueError(
                "Unanswerable cases must not contain expected sources or facts"
            )

        if self.category == "unanswerable" and self.answerable:
            raise ValueError("Unanswerable category requires answerable=False")

        if self.category == "follow_up" and not self.history:
            raise ValueError("Follow-up cases require conversation history")

        return self


class EvaluationDataset(BaseModel):
    """A collection of evaluation cases with unique IDs."""

    model_config = ConfigDict(extra="forbid")

    cases: list[EvaluationCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> Self:
        case_ids = [case.id for case in self.cases]

        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Evaluation case IDs must be unique")

        return self
