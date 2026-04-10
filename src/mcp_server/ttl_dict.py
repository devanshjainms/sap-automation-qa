# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
TTL-based dictionary that evicts entries after a configurable timeout.
"""

from __future__ import annotations
import time
from typing import Iterator, TypeVar

V = TypeVar("V")

_DEFAULT_TTL = 7200
_DEFAULT_MAX_SIZE = 100


class TtlDict(dict[str, V]):
    """Dict with automatic TTL eviction and size limit.

    Entries expire after ``ttl_seconds`` and are lazily evicted on access.
    If ``max_size`` is exceeded, the oldest entry is removed.

    :param ttl_seconds: Time-to-live in seconds (default 3600).
    :param max_size: Maximum number of entries (default 100).
    """

    def __init__(
        self,
        ttl_seconds: float = _DEFAULT_TTL,
        max_size: int = _DEFAULT_MAX_SIZE,
    ) -> None:
        super().__init__()
        self._ttl = ttl_seconds
        self._max_size = max_size
        self._timestamps: dict[str, float] = {}

    def __setitem__(self, key: str, value: V) -> None:
        self._evict_expired()
        if len(self) >= self._max_size and key not in self:
            oldest = min(self._timestamps, key=self._timestamps.get)  # type: ignore[arg-type]
            self.pop(oldest, None)
        super().__setitem__(key, value)
        self._timestamps[key] = time.monotonic()

    def __getitem__(self, key: str) -> V:
        self._evict_if_expired(key)
        return super().__getitem__(key)

    def __contains__(self, key: object) -> bool:
        if isinstance(key, str):
            self._evict_if_expired(key)
        return super().__contains__(key)

    def get(self, key: str, default: V | None = None) -> V | None:  # type: ignore[override]
        if isinstance(key, str):
            self._evict_if_expired(key)
        return super().get(key, default)

    def pop(self, key: str, *args) -> V:  # type: ignore[override]
        self._timestamps.pop(key, None)
        return super().pop(key, *args)

    def __delitem__(self, key: str) -> None:
        self._timestamps.pop(key, None)
        super().__delitem__(key)

    def __iter__(self) -> Iterator[str]:
        self._evict_expired()
        return super().__iter__()

    def __len__(self) -> int:
        self._evict_expired()
        return super().__len__()

    def _evict_if_expired(self, key: str) -> None:
        ts = self._timestamps.get(key)
        if ts is not None and (time.monotonic() - ts) > self._ttl:
            super().pop(key, None)
            self._timestamps.pop(key, None)

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [k for k, ts in self._timestamps.items() if (now - ts) > self._ttl]
        for k in expired:
            super().pop(k, None)
            self._timestamps.pop(k, None)
