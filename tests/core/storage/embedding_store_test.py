# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for EmbeddingStore (sqlite-vec backed vector storage)."""

import math
import struct
from pathlib import Path
from typing import Generator, List

import pytest
from src.core.storage.embedding_store import (
    EmbeddingStore,
    _deserialize_f32,
    _serialize_f32,
)

DIMS = 4


@pytest.fixture
def es(tmp_path: Path) -> Generator[EmbeddingStore, None, None]:
    """Create an EmbeddingStore with small dimensions for testing."""
    store = EmbeddingStore(db_path=tmp_path / "vec.db", dimensions=DIMS)
    yield store
    store.close()


@pytest.fixture
def es_memory() -> Generator[EmbeddingStore, None, None]:
    """In-memory EmbeddingStore for fast tests."""
    store = EmbeddingStore(db_path=":memory:", dimensions=DIMS)
    yield store
    store.close()


def _vec(x: float, y: float, z: float, w: float) -> List[float]:
    """Build a 4-d vector."""
    return [x, y, z, w]


class TestSerialization:
    """Tests for float32 (de)serialization helpers."""

    def test_round_trip(self) -> None:
        """Serialize then deserialize yields the same values."""
        original = [1.0, 2.5, -3.0, 0.0]
        data = _serialize_f32(original)
        assert len(data) == 16  # 4 floats × 4 bytes
        restored = _deserialize_f32(data)
        for a, b in zip(original, restored):
            assert abs(a - b) < 1e-6

    def test_empty_vector(self) -> None:
        """Empty vector round-trips correctly."""
        data = _serialize_f32([])
        assert data == b""
        assert _deserialize_f32(data) == []


class TestStoreAndRetrieve:
    """Tests for store, get, has, count, delete operations."""

    def test_store_and_get(self, es_memory: EmbeddingStore) -> None:
        """Store an embedding and retrieve it."""
        vec = _vec(1.0, 0.0, 0.0, 0.0)
        es_memory.store("R-1", "rule", vec)
        got = es_memory.get("R-1", "rule")
        assert got is not None
        for a, b in zip(vec, got):
            assert abs(a - b) < 1e-6

    def test_has_true(self, es_memory: EmbeddingStore) -> None:
        """has() returns True for stored item."""
        es_memory.store("R-1", "rule", _vec(1, 0, 0, 0))
        assert es_memory.has("R-1", "rule") is True

    def test_has_false(self, es_memory: EmbeddingStore) -> None:
        """has() returns False for missing item."""
        assert es_memory.has("R-999", "rule") is False

    def test_get_missing(self, es_memory: EmbeddingStore) -> None:
        """get() returns None for missing item."""
        assert es_memory.get("R-999", "rule") is None

    def test_count(self, es_memory: EmbeddingStore) -> None:
        """count() reflects stored items."""
        assert es_memory.count() == 0
        es_memory.store("R-1", "rule", _vec(1, 0, 0, 0))
        es_memory.store("R-2", "rule", _vec(0, 1, 0, 0))
        assert es_memory.count() == 2

    def test_delete(self, es_memory: EmbeddingStore) -> None:
        """delete() removes the embedding and returns True."""
        es_memory.store("R-1", "rule", _vec(1, 0, 0, 0))
        assert es_memory.delete("R-1", "rule") is True
        assert es_memory.has("R-1", "rule") is False
        assert es_memory.count() == 0

    def test_delete_missing(self, es_memory: EmbeddingStore) -> None:
        """delete() returns False when item does not exist."""
        assert es_memory.delete("R-999", "rule") is False

    def test_update_embedding(self, es_memory: EmbeddingStore) -> None:
        """Storing again with the same key updates the vector."""
        es_memory.store("R-1", "rule", _vec(1, 0, 0, 0))
        es_memory.store("R-1", "rule", _vec(0, 1, 0, 0))
        assert es_memory.count() == 1
        got = es_memory.get("R-1", "rule")
        assert got is not None
        assert abs(got[1] - 1.0) < 1e-6

    def test_different_types_same_id(self, es_memory: EmbeddingStore) -> None:
        """Same item_id with different item_type are distinct."""
        es_memory.store("X-1", "rule", _vec(1, 0, 0, 0))
        es_memory.store("X-1", "playbook", _vec(0, 1, 0, 0))
        assert es_memory.count() == 2
        r = es_memory.get("X-1", "rule")
        p = es_memory.get("X-1", "playbook")
        assert r is not None
        assert p is not None
        assert abs(r[0] - 1.0) < 1e-6
        assert abs(p[1] - 1.0) < 1e-6


class TestDimensionValidation:
    """Tests for dimension mismatch errors."""

    def test_store_wrong_dimensions(self, es_memory: EmbeddingStore) -> None:
        """store() rejects vectors with wrong dimensions."""
        with pytest.raises(ValueError, match="Expected 4 dimensions"):
            es_memory.store("R-1", "rule", [1.0, 0.0])

    def test_search_wrong_dimensions(self, es_memory: EmbeddingStore) -> None:
        """search() rejects query vectors with wrong dimensions."""
        with pytest.raises(ValueError, match="Expected 4 dimensions"):
            es_memory.search([1.0, 0.0])


class TestSearch:
    """Tests for cosine similarity KNN search."""

    def test_exact_match_is_closest(self, es_memory: EmbeddingStore) -> None:
        """Exact same vector has distance ~0."""
        es_memory.store("R-1", "rule", _vec(1, 0, 0, 0))
        es_memory.store("R-2", "rule", _vec(0, 1, 0, 0))
        results = es_memory.search(_vec(1, 0, 0, 0), limit=2)
        assert len(results) == 2
        assert results[0][0] == "R-1"
        assert results[0][2] < 0.01  # distance near 0

    def test_similarity_order(self, es_memory: EmbeddingStore) -> None:
        """More similar items have lower distance."""
        es_memory.store("R-1", "rule", _vec(1, 0, 0, 0))
        es_memory.store("R-2", "rule", _vec(0.9, 0.1, 0, 0))
        es_memory.store("R-3", "rule", _vec(0, 1, 0, 0))
        results = es_memory.search(_vec(1, 0, 0, 0), limit=3)
        ids = [r[0] for r in results]
        assert ids[0] == "R-1"
        assert ids[1] == "R-2"
        assert ids[2] == "R-3"

    def test_filter_by_type(self, es_memory: EmbeddingStore) -> None:
        """item_type filter excludes non-matching types."""
        es_memory.store("R-1", "rule", _vec(1, 0, 0, 0))
        es_memory.store("PB-1", "playbook", _vec(0.9, 0.1, 0, 0))
        results = es_memory.search(_vec(1, 0, 0, 0), item_type="rule", limit=10)
        ids = {r[0] for r in results}
        assert "R-1" in ids
        assert "PB-1" not in ids

    def test_limit_caps_results(self, es_memory: EmbeddingStore) -> None:
        """limit parameter restricts result count."""
        for i in range(10):
            es_memory.store(f"R-{i}", "rule", _vec(float(i), 1, 0, 0))
        results = es_memory.search(_vec(5, 1, 0, 0), limit=3)
        assert len(results) <= 3

    def test_empty_store_returns_empty(self, es_memory: EmbeddingStore) -> None:
        """Search on empty store returns empty list."""
        results = es_memory.search(_vec(1, 0, 0, 0))
        assert results == []


class TestFilePersistence:
    """Tests for file-backed database persistence."""

    def test_data_survives_reopen(self, tmp_path: Path) -> None:
        """Embeddings persist after close and reopen."""
        db_path = tmp_path / "persist.db"
        store1 = EmbeddingStore(db_path=db_path, dimensions=DIMS)
        store1.store("R-1", "rule", _vec(1, 0, 0, 0))
        store1.close()

        store2 = EmbeddingStore(db_path=db_path, dimensions=DIMS)
        assert store2.has("R-1", "rule") is True
        got = store2.get("R-1", "rule")
        assert got is not None
        assert abs(got[0] - 1.0) < 1e-6
        store2.close()

    def test_search_after_reopen(self, tmp_path: Path) -> None:
        """KNN search works after reopen."""
        db_path = tmp_path / "persist2.db"
        store1 = EmbeddingStore(db_path=db_path, dimensions=DIMS)
        store1.store("R-1", "rule", _vec(1, 0, 0, 0))
        store1.store("R-2", "rule", _vec(0, 1, 0, 0))
        store1.close()

        store2 = EmbeddingStore(db_path=db_path, dimensions=DIMS)
        results = store2.search(_vec(1, 0, 0, 0), limit=2)
        assert results[0][0] == "R-1"
        store2.close()


class TestTextHash:
    """Tests for text_hash staleness tracking."""

    def test_text_hash_stored(self, es_memory: EmbeddingStore) -> None:
        """text_hash is stored in metadata."""
        es_memory.store("R-1", "rule", _vec(1, 0, 0, 0), text_hash="abc123")
        row = es_memory._conn.execute(
            "SELECT text_hash FROM embedding_metadata " "WHERE item_id = ? AND item_type = ?",
            ("R-1", "rule"),
        ).fetchone()
        assert row is not None
        assert row[0] == "abc123"

    def test_text_hash_updated(self, es_memory: EmbeddingStore) -> None:
        """text_hash is updated on re-store."""
        es_memory.store("R-1", "rule", _vec(1, 0, 0, 0), text_hash="v1")
        es_memory.store("R-1", "rule", _vec(0, 1, 0, 0), text_hash="v2")
        row = es_memory._conn.execute(
            "SELECT text_hash FROM embedding_metadata " "WHERE item_id = ? AND item_type = ?",
            ("R-1", "rule"),
        ).fetchone()
        assert row is not None
        assert row[0] == "v2"


class TestDimensionMismatch:
    """Tests for dimension validation on database reopen."""

    def test_reopen_with_different_dims_raises(self, tmp_path: Path) -> None:
        """Opening an existing DB with mismatched dims raises."""
        db_path = tmp_path / "dim_mismatch.db"
        store1 = EmbeddingStore(db_path=db_path, dimensions=4)
        store1.store("R-1", "rule", _vec(1, 0, 0, 0))
        store1.close()

        with pytest.raises(RuntimeError, match="4 dimensions"):
            EmbeddingStore(db_path=db_path, dimensions=8)

    def test_reopen_with_same_dims_succeeds(self, tmp_path: Path) -> None:
        """Opening an existing DB with same dims works fine."""
        db_path = tmp_path / "same_dims.db"
        store1 = EmbeddingStore(db_path=db_path, dimensions=DIMS)
        store1.close()
        store2 = EmbeddingStore(db_path=db_path, dimensions=DIMS)
        assert store2.count() == 0
        store2.close()

    def test_zero_dimensions_rejected(self) -> None:
        """dimensions=0 raises ValueError."""
        with pytest.raises(ValueError, match="positive integer"):
            EmbeddingStore(db_path=":memory:", dimensions=0)

    def test_negative_dimensions_rejected(self) -> None:
        """Negative dimensions raises ValueError."""
        with pytest.raises(ValueError, match="positive integer"):
            EmbeddingStore(db_path=":memory:", dimensions=-1)
