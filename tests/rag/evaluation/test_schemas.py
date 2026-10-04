import json

import pytest
from pydantic import ValidationError

from pole_position.chat.schemas import ChatHistoryMessage
from pole_position.rag.evaluation.schemas import (
    EvaluationCase,
    EvaluationDataset,
    ExpectedSource,
)


@pytest.fixture
def source_payload() -> dict[str, object]:
    return {
        "document_id": "fia-f1-2026-section-b-issue-08",
        "source_kind": "clause",
        "clause_identifier": "B6.3.6",
        "pdf_pages": [58],
    }


@pytest.fixture
def case_payload(source_payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": "sporting_tyres_001",
        "category": "semantic",
        "question": "How many tyre changes are required per race?",
        "answerable": True,
        "expected_sources": [source_payload],
        "expected_facts": [
            "Unless intermediate or wet-weather tyres are used, drivers must use "
            "at least two different dry-weather tyre specifications."
        ],
    }


@pytest.mark.parametrize(
    "metadata",
    [
        {"source_kind": "clause", "clause_identifier": "B6.3.6"},
        {"source_kind": "appendix", "appendix_identifier": "B4"},
        {"source_kind": "preamble"},
    ],
)
def test_valid_source_kinds(metadata: dict[str, object]) -> None:
    source = ExpectedSource.model_validate({
        "document_id": "example-document",
        "pdf_pages": [4, 5],
        **metadata,
    })

    assert source.source_kind == metadata["source_kind"]
    assert source.pdf_pages == [4, 5]
    assert source.clause_identifier == metadata.get("clause_identifier")
    assert source.appendix_identifier == metadata.get("appendix_identifier")


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        ({"source_kind": "clause"}, "requires a clause identifier"),
        ({"source_kind": "appendix"}, "requires an appendix identifier"),
        (
            {
                "source_kind": "clause",
                "clause_identifier": "B6.3.6",
                "appendix_identifier": "B4",
            },
            "cannot contain an appendix identifier",
        ),
        (
            {
                "source_kind": "appendix",
                "appendix_identifier": "B4",
                "clause_identifier": "B6.3.6",
            },
            "cannot contain a clause identifier",
        ),
        (
            {"source_kind": "preamble", "clause_identifier": "A1.1"},
            "cannot contain identifiers",
        ),
        (
            {"source_kind": "preamble", "appendix_identifier": "A1"},
            "cannot contain identifiers",
        ),
    ],
)
def test_source_rejects_missing_or_mixed_metadata(
    metadata: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        ExpectedSource.model_validate({
            "document_id": "example-document",
            "pdf_pages": [4],
            **metadata,
        })


@pytest.mark.parametrize(
    "overrides",
    [
        {"document_id": "   "},
        {"source_kind": "article"},
        {"clause_identifier": "B6"},
        {"clause_identifier": "G6.3.6"},
        {
            "source_kind": "appendix",
            "clause_identifier": None,
            "appendix_identifier": "B4.1",
        },
        {"pdf_pages": []},
        {"pdf_pages": [0]},
        {"pdf_pages": [-1]},
        {"pdf_pages": [58, 58]},
        {"unexpected": True},
    ],
)
def test_source_rejects_invalid_fields(
    source_payload: dict[str, object], overrides: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        ExpectedSource.model_validate({**source_payload, **overrides})


def test_valid_answerable_case_has_typed_sources_and_empty_history(
    case_payload: dict[str, object],
) -> None:
    case = EvaluationCase.model_validate(case_payload)

    assert case.id == "sporting_tyres_001"
    assert case.answerable is True
    assert case.history == []
    assert isinstance(case.expected_sources[0], ExpectedSource)
    assert case.expected_sources[0].clause_identifier == "B6.3.6"
    assert len(case.expected_facts) == 1


@pytest.mark.parametrize("field", ["expected_sources", "expected_facts"])
@pytest.mark.parametrize("omit", [False, True])
def test_answerable_case_requires_sources_and_facts(
    case_payload: dict[str, object], field: str, omit: bool
) -> None:
    if omit:
        case_payload.pop(field)
    else:
        case_payload[field] = []

    with pytest.raises(ValidationError, match="Answerable cases require"):
        EvaluationCase.model_validate(case_payload)


def test_unanswerable_case_can_omit_sources_facts_and_history() -> None:
    case = EvaluationCase(
        id="unsupported_001",
        category="unanswerable",
        question="Who will win the next race?",
        answerable=False,
    )

    assert case.expected_sources == []
    assert case.expected_facts == []
    assert case.history == []


@pytest.mark.parametrize("field", ["expected_sources", "expected_facts"])
def test_unanswerable_case_rejects_expected_evidence_or_facts(
    case_payload: dict[str, object], field: str
) -> None:
    payload = {
        "id": "unsupported_001",
        "category": "unanswerable",
        "question": "Who will win the next race?",
        "answerable": False,
        field: case_payload[field],
    }
    with pytest.raises(ValidationError, match="must not contain expected"):
        EvaluationCase.model_validate(payload)


def test_unanswerable_category_cannot_be_marked_answerable(
    case_payload: dict[str, object],
) -> None:
    case_payload["category"] = "unanswerable"
    with pytest.raises(ValidationError, match="requires answerable=False"):
        EvaluationCase.model_validate(case_payload)


def test_follow_up_preserves_chronological_history_and_latest_question(
    case_payload: dict[str, object],
) -> None:
    previous = [
        {"role": "user", "content": "How many tyre changes are required?"},
        {"role": "assistant", "content": "Two dry specifications are required."},
    ]
    case = EvaluationCase.model_validate({
        **case_payload,
        "category": "follow_up",
        "question": "What happens if a driver does not comply?",
        "history": previous,
    })

    assert all(isinstance(item, ChatHistoryMessage) for item in case.history)
    assert [item.model_dump() for item in case.history] == previous
    assert case.question == "What happens if a driver does not comply?"
    assert len(case.history) == 2


def test_follow_up_requires_history(case_payload: dict[str, object]) -> None:
    case_payload["category"] = "follow_up"
    with pytest.raises(ValidationError, match="require conversation history"):
        EvaluationCase.model_validate(case_payload)


@pytest.mark.parametrize(
    "history",
    [
        None,
        [{"role": "system", "content": "Not an allowed history role"}],
        [{"role": "user", "content": "   "}],
        [{"role": "assistant", "content": "x" * 8_001}],
        [{"role": "user", "content": "Question"}] * 11,
    ],
)
def test_case_rejects_invalid_history(
    case_payload: dict[str, object], history: object
) -> None:
    with pytest.raises(ValidationError):
        EvaluationCase.model_validate({**case_payload, "history": history})


@pytest.mark.parametrize(
    "overrides",
    [
        {"id": "   "},
        {"question": "   "},
        {"question": "x" * 4_001},
        {"category": "unknown"},
        {"expected_facts": ["   "]},
        {"unexpected": True},
    ],
)
def test_case_rejects_invalid_fields(
    case_payload: dict[str, object], overrides: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        EvaluationCase.model_validate({**case_payload, **overrides})


def test_default_history_lists_are_independent(case_payload: dict[str, object]) -> None:
    first = EvaluationCase.model_validate(case_payload)
    second = EvaluationCase.model_validate(case_payload)
    first.history.append(ChatHistoryMessage(role="user", content="Earlier question"))

    assert second.history == []


def test_dataset_loads_from_json_and_round_trips(
    case_payload: dict[str, object],
) -> None:
    payload = {
        "cases": [
            case_payload,
            {
                "id": "unsupported_001",
                "category": "unanswerable",
                "question": "Who will win the next race?",
                "answerable": False,
            },
        ]
    }
    dataset = EvaluationDataset.model_validate_json(json.dumps(payload))

    assert len(dataset.cases) == 2
    assert all(isinstance(case, EvaluationCase) for case in dataset.cases)
    assert dataset.cases[0].expected_sources[0].pdf_pages == [58]
    assert dataset.cases[1].expected_sources == []
    assert EvaluationDataset.model_validate_json(dataset.model_dump_json()) == dataset


@pytest.mark.parametrize("padded_id", [False, True])
def test_dataset_rejects_duplicate_case_ids(
    case_payload: dict[str, object], padded_id: bool
) -> None:
    duplicate = {
        **case_payload,
        "id": " sporting_tyres_001 " if padded_id else "sporting_tyres_001",
    }
    with pytest.raises(ValidationError, match="case IDs must be unique"):
        EvaluationDataset.model_validate({"cases": [case_payload, duplicate]})


@pytest.mark.parametrize(
    "payload",
    [{"cases": []}, {}, {"cases": [], "unexpected": True}],
)
def test_dataset_rejects_empty_or_missing_cases(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        EvaluationDataset.model_validate(payload)


def test_dataset_rejects_unknown_fields(case_payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        EvaluationDataset.model_validate({"cases": [case_payload], "unexpected": True})
