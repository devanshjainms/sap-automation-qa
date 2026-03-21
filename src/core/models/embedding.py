# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Embedding provider protocol for text-to-vector conversion."""

from typing import List, Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for generating text embeddings.

    Implementations may use Azure OpenAI, sentence-transformers, or
    any other embedding model. The ``dimensions`` property must match
    the ``EmbeddingStore`` configuration.
    """

    @property
    def dimensions(self) -> int:
        """Return the number of dimensions produced by this provider."""
        ...

    def embed(self, text: str) -> List[float]:
        """Generate an embedding vector for a single text.

        :param text: Input text to embed.
        :returns: Float vector of length ``dimensions``.
        """
        ...

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embedding vectors for multiple texts.

        :param texts: Input texts to embed.
        :returns: List of float vectors, one per input text.
        """
        ...
