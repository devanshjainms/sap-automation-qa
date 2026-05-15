# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
In-process embedding provider using fastembed (ONNX Runtime).
"""

from __future__ import annotations
import logging
import os
from typing import TYPE_CHECKING, List, Protocol, runtime_checkable
import numpy as np
from fastembed import TextEmbedding
from fastembed.common.model_description import ModelSource, PoolingType

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "intfloat/e5-base-v2"
_DEFAULT_ONNX_FILE = "onnx/model_O4.onnx"
_DEFAULT_MODEL_PATH = os.environ.get("EMBEDDING_MODEL_PATH", "")


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
    In-process embedding using fastembed + Microsoft E5 (ONNX).

    :param model_name: HuggingFace model name.
    :param onnx_file: Path to the ONNX model file within the HF repo.
    """

    def __init__(
        self,
        model_name: str = _DEFAULT_MODEL,
        onnx_file: str = _DEFAULT_ONNX_FILE,
    ) -> None:
        self._model_name = model_name
        self._onnx_file = onnx_file
        self._model: TextEmbedding | None = None
        self._dimensions: int = 0

    def _ensure_loaded(self) -> None:
        """Load the model on first use.

        When ``EMBEDDING_MODEL_PATH`` is set (Docker deployment), loads
        directly from the local path — no HuggingFace download.
        Otherwise downloads on first call (local dev).
        """
        if self._model is not None:
            return

        TextEmbedding.add_custom_model(
            model=self._model_name,
            pooling=PoolingType.MEAN,
            normalization=True,
            sources=ModelSource(hf=self._model_name),
            dim=768,
            model_file=self._onnx_file,
            description="Microsoft Research E5 encoder via ONNX",
            license="mit",
            size_in_gb=0.218,
        )

        model_kwargs: dict = {"model_name": self._model_name}
        if _DEFAULT_MODEL_PATH:
            model_kwargs["specific_model_path"] = _DEFAULT_MODEL_PATH
            logger.info(
                "Loading embedding model: %s from %s",
                self._model_name,
                _DEFAULT_MODEL_PATH,
            )
        else:
            logger.info("Loading embedding model: %s (downloading)", self._model_name)

        self._model = TextEmbedding(**model_kwargs)
        test_vec = list(self._model.embed(["test"]))[0]
        self._dimensions = len(test_vec)
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
        Generate an embedding for a query text.

        :param text: Input query text.
        :returns: Float vector of length ``dimensions``.
        """
        self._ensure_loaded()
        assert self._model is not None
        prefixed = f"query: {text}"
        vectors = list(self._model.embed([prefixed]))
        return vectors[0].tolist()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for document/passage texts.

        :param texts: Input document texts.
        :returns: List of float vectors.
        """
        self._ensure_loaded()
        assert self._model is not None
        prefixed = [f"passage: {t}" for t in texts]
        vectors = list(self._model.embed(prefixed))
        return [v.tolist() for v in vectors]


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
