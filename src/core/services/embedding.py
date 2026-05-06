# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
OpenAI-compatible embedding provider using httpx.
"""

from __future__ import annotations
import logging
from typing import List
import httpx

logger = logging.getLogger(__name__)


class OpenAICompatibleEmbedding:
    """
    Embedding provider targeting an OpenAI-compatible ``/embeddings`` endpoint.

    :param base_url: Base URL of the API (e.g. ``https://my.openai.azure.com``
        or ``http://localhost:11434/v1``).
    :param model: Model or deployment name.
    :param api_key: API key (use ``"ollama"`` for local Ollama).
    :param dimensions: Expected embedding dimensions.
    :param timeout: HTTP timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        dimensions: int = 768,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._dimensions = dimensions
        self._client = httpx.Client(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=timeout,
        )

    @property
    def dimensions(self) -> int:
        """Return the configured embedding dimensions."""
        return self._dimensions

    def embed(self, text: str) -> List[float]:
        """Generate an embedding vector for a single text.

        :param text: Input text to embed.
        :returns: Float vector of length ``dimensions``.
        """
        vectors = self.embed_batch([text])
        return vectors[0]

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embedding vectors for multiple texts.

        :param texts: Input texts to embed.
        :returns: List of float vectors, one per input text.
        """
        payload = {"input": texts, "model": self._model}
        resp = self._client.post("/embeddings", json=payload)
        resp.raise_for_status()
        data = resp.json()
        results: List[List[float]] = []
        for item in sorted(data["data"], key=lambda x: x["index"]):
            results.append(item["embedding"])
        return results
