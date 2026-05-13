# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
In-process embedding provider using sentence-transformers.
"""

from __future__ import annotations
import os
import onnxruntime
import logging
import numpy as np
from typing import List, Protocol, runtime_checkable
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = os.getenv("EMBEDDING_MODEL", "microsoft/harrier-oss-v1-270m")
_QUERY_PROMPT_NAME = "web_search_query"


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for generating text embeddings."""

    @property
    def dimensions(self) -> int:
        """Return the number of dimensions produced by this provider."""
        raise NotImplementedError("dimensions property must be implemented")

    def embed(self, text: str) -> List[float]:
        """Generate an embedding vector for a single text."""
        raise NotImplementedError("embed() method must be implemented")

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embedding vectors for multiple texts."""
        raise NotImplementedError("embed_batch() method must be implemented")


class LocalEmbeddingProvider:
    """
    In-process embedding using sentence-transformers + Microsoft Harrier.

    :param model_name: HuggingFace model name.
    :param query_prompt_name: Prompt name for query encoding.
        Set to empty string for models without prompt-based encoding.
    """

    def __init__(
        self,
        model_name: str = _DEFAULT_MODEL,
        query_prompt_name: str = _QUERY_PROMPT_NAME,
    ) -> None:
        self._model_name = model_name
        self._query_prompt_name = query_prompt_name
        self._model: SentenceTransformer | None = None
        self._dimensions: int = 0

    def _ensure_loaded(self) -> None:
        """Load the model on first use."""
        if self._model is not None:
            return

        logger.info("Loading embedding model: %s", self._model_name)
        self._model = SentenceTransformer(
            self._model_name,
            model_kwargs={"dtype": "auto"},
        )
        dim = self._model.get_embedding_dimension()
        self._dimensions = dim if dim is not None else 0
        logger.info(
            "Embedding model loaded: %s (%d dimensions)",
            self._model_name,
            self._dimensions,
        )

    @property
    def dimensions(self) -> int:
        """Return the number of dimensions produced by this model."""
        self._ensure_loaded()
        return self._dimensions

    def embed(self, text: str) -> List[float]:
        """
        Generate an embedding vector for a query text.

        :param text: Input query text to embed.
        :returns: Float vector of length ``dimensions``.
        """
        self._ensure_loaded()
        assert self._model is not None
        if self._query_prompt_name:
            vector = self._model.encode(
                text,
                normalize_embeddings=True,
                prompt_name=self._query_prompt_name,
            )
        else:
            vector = self._model.encode(text, normalize_embeddings=True)
        return vector.tolist()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embedding vectors for multiple document texts.

        :param texts: Input document texts to embed.
        :returns: List of float vectors, one per input text.
        """
        self._ensure_loaded()
        assert self._model is not None
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return vectors.tolist()


def cosine_similarity_matrix(
    query_vec: np.ndarray,
    corpus_vecs: np.ndarray,
) -> np.ndarray:
    """
    Compute cosine similarity between a query and corpus vectors.

    :param query_vec: Shape ``(dims,)``.
    :param corpus_vecs: Shape ``(n, dims)``.
    :returns: Shape ``(n,)`` similarity scores.
    """
    return corpus_vecs @ query_vec
