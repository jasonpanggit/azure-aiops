from __future__ import annotations

import math
import time
from collections import OrderedDict
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from threading import RLock
from typing import Any


@dataclass(frozen=True)
class CacheStats:
    hits: int
    misses: int
    size: int

    @property
    def hit_ratio(self) -> float:
        requests = self.hits + self.misses
        return self.hits / requests if requests else 0.0


@dataclass
class _Entry:
    value: Any
    expires_at: float
    knowledge_version: str


class SemanticCache:
    def __init__(
        self,
        *,
        max_entries: int = 256,
        ttl_seconds: float = 300,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            isinstance(max_entries, bool)
            or not isinstance(max_entries, int)
            or max_entries < 1
            or isinstance(ttl_seconds, bool)
            or not isinstance(ttl_seconds, (int, float))
            or not math.isfinite(ttl_seconds)
            or ttl_seconds <= 0
        ):
            raise ValueError("Semantic cache bounds and TTL must be positive")
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._lock = RLock()

    def get(self, key: str, *, knowledge_version: str = "") -> Any | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return None
            if entry.expires_at <= self.clock() or (
                knowledge_version and entry.knowledge_version != knowledge_version
            ):
                del self._entries[key]
                self._misses += 1
                return None
            self._entries.move_to_end(key)
            self._hits += 1
            return deepcopy(entry.value)

    def set(self, key: str, value: Any, *, knowledge_version: str = "") -> None:
        with self._lock:
            self._entries[key] = _Entry(
                value=deepcopy(value),
                expires_at=self.clock() + self.ttl_seconds,
                knowledge_version=knowledge_version,
            )
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(self._hits, self._misses, len(self._entries))
