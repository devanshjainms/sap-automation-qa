# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for EmbeddingAdapter (AF BaseEmbeddingClient → EmbeddingProvider)."""

from __future__ import annotations

import asyncio
from typing import Any, Sequence
from unittest.mock import AsyncMock

import pytest

from agent_framework import BaseEmbeddingClient, Embedding, GeneratedEmbeddings
from src.agents.providers.embedding_adapter import EmbeddingAdapter
from src.core.models.embedding import EmbeddingProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeEmbeddingClient(BaseEmbeddingClient[str, list[float], Any]):
    """Minimal stub that extends BaseEmbeddingClient."""

    def __init__(self, vectors: list[list[float]]) -> None:
        super().__init__()
        self._vectors = vectors
        self.calls: list[Sequence[str]] = []

    async def get_embeddings(
        self,
        values: Sequence[str],
        *,
        options: Any = None,
    ) -> GeneratedEmbeddings:
        self.calls.append(values)
        embeddings = [
            Embedding(vector=self._vectors[i], dimensions=len(self._vectors[i]))
            for i in range(len(values))
        ]
        return GeneratedEmbeddings(embeddings)


class FailingClient(BaseEmbeddingClient[str, list[float], Any]):
    """Client whose get_embeddings always raises."""

    def __init__(self) -> None:
        super().__init__()

    async def get_embeddings(self, values: Sequence[str], *, options: Any = None) -> GeneratedEmbeddings:
        raise ConnectionError("API is down")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmbeddingAdapterProtocol:
    """The adapter must satisfy EmbeddingProvider."""

    def test_satisfies_protocol(self):
        client = FakeEmbeddingClient([[0.0]])
        adapter = EmbeddingAdapter(client, dimensions=1)
        assert isinstance(adapter, EmbeddingProvider)

    def test_dimensions(self):
        client = FakeEmbeddingClient([[0.0, 0.1, 0.2]])
        adapter = EmbeddingAdapter(client, dimensions=3)
        assert adapter.dimensions == 3


class TestEmbed:
    """Single text embedding."""

    def test_embed_single(self):
        client = FakeEmbeddingClient([[0.1, 0.2, 0.3]])
        adapter = EmbeddingAdapter(client, dimensions=3)
        result = adapter.embed("hello world")
        assert result == [0.1, 0.2, 0.3]
        assert client.calls == [["hello world"]]

    def test_embed_delegates_to_batch(self):
        client = FakeEmbeddingClient([[1.0, 2.0]])
        adapter = EmbeddingAdapter(client, dimensions=2)
        result = adapter.embed("test")
        assert result == [1.0, 2.0]


class TestEmbedBatch:
    """Batch embedding."""

    def test_batch_multiple(self):
        client = FakeEmbeddingClient([[1.0, 0.0], [0.0, 1.0]])
        adapter = EmbeddingAdapter(client, dimensions=2)
        result = adapter.embed_batch(["a", "b"])
        assert result == [[1.0, 0.0], [0.0, 1.0]]

    def test_batch_empty(self):
        client = FakeEmbeddingClient([])
        adapter = EmbeddingAdapter(client, dimensions=3)
        assert adapter.embed_batch([]) == []
        assert client.calls == []

    def test_api_error_wraps_in_runtime_error(self):
        adapter = EmbeddingAdapter(FailingClient(), dimensions=3)
        with pytest.raises(RuntimeError, match="Embedding API call failed"):
            adapter.embed_batch(["test"])


class TestRunAsync:
    """Verify _run_async works both outside and inside event loops."""

    def test_outside_event_loop(self):
        async def coro():
            return 42

        assert EmbeddingAdapter._run_async(coro()) == 42

    def test_inside_event_loop(self):
        async def outer():
            async def inner():
                return 99

            return EmbeddingAdapter._run_async(inner())

        result = asyncio.run(outer())
        assert result == 99
