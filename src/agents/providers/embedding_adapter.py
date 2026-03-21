# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Adapter: wraps Agent Framework's async ``BaseEmbeddingClient`` to
satisfy the sync ``EmbeddingProvider`` protocol.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, List
import concurrent.futures
from agent_framework import BaseEmbeddingClient, Embedding

logger = logging.getLogger(__name__)


class EmbeddingAdapter:
    """Sync adapter over Agent Framework's ``BaseEmbeddingClient``.

    :param client: Any AF embedding client (Azure OpenAI, OpenAI, Ollama).
    :param dimensions: Vector dimensions produced by the model.
    """

    def __init__(self, client: BaseEmbeddingClient[Any, Any, Any], *, dimensions: int) -> None:
        self._client = client
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        """Number of dimensions produced by the underlying model."""
        return self._dimensions

    def embed(self, text: str) -> List[float]:
        """Embed a single text synchronously.

        :param text: Input text.
        :returns: Float vector of length ``dimensions``.
        :raises RuntimeError: If the API call fails.
        """
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts synchronously.

        :param texts: Input texts.
        :returns: List of float vectors.
        :raises RuntimeError: If the API call fails.
        """
        if not texts:
            return []
        try:
            return [
                self._extract_vector(e) for e in self._run_async(self._client.get_embeddings(texts))
            ]
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Embedding API call failed: {exc}") from exc

    @staticmethod
    def _extract_vector(embedding: Embedding) -> List[float]:
        """Pull the raw float list from an AF ``Embedding`` object."""
        vec = embedding.vector
        if isinstance(vec, list):
            return vec
        return list(vec)

    @staticmethod
    def _run_async(coro):
        """Run an async coroutine from sync context."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()
        return asyncio.run(coro)
