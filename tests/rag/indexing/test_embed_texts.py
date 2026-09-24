from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, call

import pytest
from openai import OpenAI

from pole_position.rag.indexing.embeddings import EMBEDDING_MODEL, embed_texts


def make_response(*items: tuple[int, list[float]]) -> SimpleNamespace:
    """Build the part of an embeddings response used by embed_texts."""
    return SimpleNamespace(
        data=[
            SimpleNamespace(index=index, embedding=vector)
            for index, vector in items
        ]
    )


def test_embed_texts_batches_inputs_and_preserves_input_order() -> None:
    client = Mock()
    client.embeddings.create.side_effect = [
        # The API may return items in a different order within a batch.
        make_response((1, [0.0, 1.0]), (0, [1.0, 0.0])),
        make_response((0, [0.5, 0.5])),
    ]

    vectors = embed_texts(
        cast(OpenAI, client),
        ["first", "second", "third"],
        batch_size=2,
    )

    assert vectors == [[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]]
    assert client.embeddings.create.call_args_list == [
        call(
            model=EMBEDDING_MODEL,
            input=["first", "second"],
            encoding_format="float",
        ),
        call(
            model=EMBEDDING_MODEL,
            input=["third"],
            encoding_format="float",
        ),
    ]


def test_embed_texts_uses_requested_model() -> None:
    client = Mock()
    client.embeddings.create.return_value = make_response((0, [1.0, 2.0]))

    assert embed_texts(cast(OpenAI, client), ["rule"], model="test-model") == [
        [1.0, 2.0]
    ]
    client.embeddings.create.assert_called_once_with(
        model="test-model",
        input=["rule"],
        encoding_format="float",
    )


def test_embed_texts_returns_empty_list_without_calling_api() -> None:
    client = Mock()

    assert embed_texts(cast(OpenAI, client), []) == []
    client.embeddings.create.assert_not_called()


@pytest.mark.parametrize("batch_size", [0, -1])
def test_embed_texts_rejects_invalid_batch_size(batch_size: int) -> None:
    client = Mock()

    with pytest.raises(ValueError, match="batch_size must be positive"):
        embed_texts(cast(OpenAI, client), ["rule"], batch_size=batch_size)

    client.embeddings.create.assert_not_called()


@pytest.mark.parametrize("texts", [[""], ["rule", "  \n  "]])
def test_embed_texts_rejects_empty_input_text(texts: list[str]) -> None:
    client = Mock()

    with pytest.raises(ValueError, match="Embedding inputs cannot be empty"):
        embed_texts(cast(OpenAI, client), texts)

    client.embeddings.create.assert_not_called()


def test_embed_texts_rejects_response_with_missing_item() -> None:
    client = Mock()
    client.embeddings.create.return_value = make_response((0, [1.0, 2.0]))

    with pytest.raises(RuntimeError, match="response count does not match"):
        embed_texts(cast(OpenAI, client), ["first", "second"])


@pytest.mark.parametrize("indexes", [(0, 0), (0, 2)])
def test_embed_texts_rejects_incomplete_response_indexes(
    indexes: tuple[int, int],
) -> None:
    client = Mock()
    client.embeddings.create.return_value = make_response(
        (indexes[0], [1.0, 0.0]),
        (indexes[1], [0.0, 1.0]),
    )

    with pytest.raises(RuntimeError, match="response indexes are incomplete"):
        embed_texts(cast(OpenAI, client), ["first", "second"])


@pytest.mark.parametrize("vector", [[], [float("nan")], [float("inf")]])
def test_embed_texts_rejects_invalid_vector(vector: list[float]) -> None:
    client = Mock()
    client.embeddings.create.return_value = make_response((0, vector))

    with pytest.raises(RuntimeError, match="invalid vector"):
        embed_texts(cast(OpenAI, client), ["rule"])


def test_embed_texts_rejects_inconsistent_dimensions_across_batches() -> None:
    client = Mock()
    client.embeddings.create.side_effect = [
        make_response((0, [1.0, 2.0])),
        make_response((0, [1.0, 2.0, 3.0])),
    ]

    with pytest.raises(RuntimeError, match="inconsistent dimensions"):
        embed_texts(cast(OpenAI, client), ["first", "second"], batch_size=1)
