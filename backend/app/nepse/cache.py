"""Tiny TTL cache used to avoid hammering the NEPSE API.

Deliberately simple: no external cache backend, just `cachetools.TTLCache`
(automatically available since `nepse-api` depends on it) plus per-key
asyncio locks so concurrent callers for the same key trigger only one
upstream fetch.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Optional

from cachetools import TTLCache


class TTLResponseCache:
    def __init__(self, maxsize: int, ttl: int) -> None:
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl)
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    async def get_or_set(self, key: str, factory: Callable[[], Awaitable[Any]]) -> Any:
        """Return cached value for `key`, or run `factory()` once and cache it.

        Raises whatever `factory()` raises; failures are not cached, so the
        next request after an error retries the upstream call.
        """
        cached: Optional[Any] = self._cache.get(key)
        if cached is not None:
            return cached

        async with self._lock_for(key):
            # Re-check: another task may have filled the cache while we waited.
            cached = self._cache.get(key)
            if cached is not None:
                return cached
            value = await factory()
            self._cache[key] = value
            return value
