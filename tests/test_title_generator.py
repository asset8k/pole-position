import json
from unittest.mock import Mock

import pytest
from openai import OpenAI

from pole_position.chat.service import make_conversation_title
from pole_position.chat.title_generator import (
    TITLE_INSTRUCTIONS,
    ConversationTitle,
    generate_conversation_title,
)


def test_generates_a_compact_title_using_the_existing_model() -> None:
    client = Mock(spec=OpenAI)
    parse = client.with_options.return_value.responses.parse
    parse.return_value = Mock(
        status="completed",
        output_parsed=ConversationTitle(title=' "Sponsorship and team compliance" '),
    )
    message = "Hey, how do my team's many sponsors affect compliance?"
    assert generate_conversation_title(message, client=client, model="test-model") == (
        "Sponsorship and team compliance"
    )
    client.with_options.assert_called_once_with(timeout=8.0, max_retries=0)
    parse.assert_called_once_with(
        model="test-model",
        instructions=TITLE_INSTRUCTIONS,
        input=json.dumps({"message": message}, ensure_ascii=False),
        text_format=ConversationTitle,
        store=False,
    )


@pytest.mark.parametrize("error", [TimeoutError("private data"), RuntimeError("private data")])
def test_model_failure_returns_short_fallback_without_logging_private_data(
    error: Exception, caplog: pytest.LogCaptureFixture,
) -> None:
    client = Mock(spec=OpenAI)
    client.with_options.return_value.responses.parse.side_effect = error
    message = "What do the regulations say about " + "sponsorship " * 20
    title = generate_conversation_title(message, client=client, model="test-model")
    assert title == make_conversation_title(message)
    assert len(title) <= 50
    assert "private data" not in caplog.text
    assert message not in caplog.text


@pytest.mark.parametrize(
    ("status", "parsed"),
    [
        ("completed", None),  # Refusal / missing structured response.
        ("incomplete", ConversationTitle(title="An unfinished title")),
        ("completed", ConversationTitle(title=" \n ")),
        ("completed", ConversationTitle(title="a" * 51)),
        ("completed", ConversationTitle(title="one two three four five six seven")),
    ],
)
def test_invalid_output_uses_fallback(status: str, parsed: ConversationTitle | None) -> None:
    client = Mock(spec=OpenAI)
    client.with_options.return_value.responses.parse.return_value = Mock(
        status=status, output_parsed=parsed,
    )
    assert generate_conversation_title("Tyre rules?", client=client, model="test-model") == "Tyre rules?"


def test_non_english_title_is_preserved_and_whitespace_normalized() -> None:
    client = Mock(spec=OpenAI)
    client.with_options.return_value.responses.parse.return_value = Mock(
        status="completed", output_parsed=ConversationTitle(title="Правила\n смены шин"),
    )
    assert generate_conversation_title("Какие правила смены шин?", client=client, model="test-model") == "Правила смены шин"
