# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for TtlDict — TTL-based dictionary with size limits."""

from __future__ import annotations
import time
from src.mcp_server.ttl_dict import TtlDict


class TestTtlDict:
    """Tests for TTL-based dictionary."""

    def test_set_and_get(self) -> None:
        d: TtlDict[str] = TtlDict(ttl_seconds=10)
        d["a"] = "hello"
        assert d["a"] == "hello"

    def test_contains(self) -> None:
        d: TtlDict[str] = TtlDict(ttl_seconds=10)
        d["x"] = "y"
        assert "x" in d
        assert "z" not in d

    def test_expiry(self) -> None:
        d: TtlDict[str] = TtlDict(ttl_seconds=0.05)
        d["k"] = "v"
        assert "k" in d
        time.sleep(0.1)
        assert "k" not in d

    def test_get_expired_returns_default(self) -> None:
        d: TtlDict[str] = TtlDict(ttl_seconds=0.05)
        d["k"] = "v"
        time.sleep(0.1)
        assert d.get("k") is None
        assert d.get("k", "fallback") == "fallback"

    def test_max_size_evicts_oldest(self) -> None:
        d: TtlDict[str] = TtlDict(ttl_seconds=60, max_size=2)
        d["a"] = "1"
        d["b"] = "2"
        d["c"] = "3"
        assert "a" not in d
        assert "b" in d
        assert "c" in d

    def test_len_after_expiry(self) -> None:
        d: TtlDict[str] = TtlDict(ttl_seconds=0.05)
        d["a"] = "1"
        d["b"] = "2"
        assert len(d) == 2
        time.sleep(0.1)
        assert len(d) == 0

    def test_delete(self) -> None:
        d: TtlDict[str] = TtlDict(ttl_seconds=60)
        d["k"] = "v"
        del d["k"]
        assert "k" not in d

    def test_pop(self) -> None:
        d: TtlDict[str] = TtlDict(ttl_seconds=60)
        d["k"] = "v"
        val = d.pop("k")
        assert val == "v"
        assert "k" not in d

    def test_pop_default(self) -> None:
        d: TtlDict[str] = TtlDict(ttl_seconds=60)
        val = d.pop("missing", "default")
        assert val == "default"

    def test_iter_excludes_expired(self) -> None:
        d: TtlDict[str] = TtlDict(ttl_seconds=0.05)
        d["a"] = "1"
        time.sleep(0.1)
        d["b"] = "2"
        keys = list(d)
        assert "a" not in keys
        assert "b" in keys

    def test_update_resets_ttl(self) -> None:
        d: TtlDict[str] = TtlDict(ttl_seconds=0.15)
        d["k"] = "v1"
        time.sleep(0.1)
        d["k"] = "v2"
        time.sleep(0.1)
        assert "k" in d
