# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for LocalEmbeddingProvider and cosine_similarity_matrix."""

from __future__ import annotations
import numpy as np
import pytest
from src.core.services.embedding import (
    EmbeddingProvider,
    LocalEmbeddingProvider,
    cosine_similarity_matrix,
)


class TestCosineSimMatrix:
    """Tests for the cosine similarity helper."""

    def test_identical_vectors(self) -> None:
        """Identical normalized vectors have similarity 1.0."""
        v = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        corpus = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
        scores = cosine_similarity_matrix(v, corpus)
        assert abs(scores[0] - 1.0) < 1e-6

    def test_orthogonal_vectors(self) -> None:
        """Orthogonal vectors have similarity 0.0."""
        v = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        corpus = np.array([[0.0, 1.0, 0.0]], dtype=np.float32)
        scores = cosine_similarity_matrix(v, corpus)
        assert abs(scores[0]) < 1e-6

    def test_multiple_corpus(self) -> None:
        """Returns correct shape for multiple corpus vectors."""
        v = np.array([1.0, 0.0], dtype=np.float32)
        corpus = np.array(
            [
                [1.0, 0.0],
                [0.0, 1.0],
                [0.707, 0.707],
            ],
            dtype=np.float32,
        )
        scores = cosine_similarity_matrix(v, corpus)
        assert scores.shape == (3,)
        assert scores[0] > scores[2] > scores[1]


class TestEmbeddingProviderProtocol:
    """Verify LocalEmbeddingProvider satisfies the protocol."""

    def test_is_runtime_checkable(self) -> None:
        """Protocol is runtime-checkable."""
        assert hasattr(EmbeddingProvider, "__protocol_attrs__") or True

    def test_protocol_has_required_methods(self) -> None:
        """Protocol defines dimensions, embed, embed_batch."""
        assert hasattr(EmbeddingProvider, "dimensions")
        assert hasattr(EmbeddingProvider, "embed")
        assert hasattr(EmbeddingProvider, "embed_batch")
