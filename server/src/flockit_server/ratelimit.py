"""In-memory login throttling. Flockit runs as one app container, so process memory is
the right place for this; no Redis (M0 allows Postgres as the only datastore)."""

from __future__ import annotations

import time
from collections import deque
from threading import Lock
from typing import Deque, Dict, Optional

WINDOW_SECONDS = 15 * 60
MAX_FAILURES_PER_EMAIL = 10
MAX_FAILURES_PER_CLIENT = 30


class FailureLimiter:
    def __init__(self, limit: int, window: float = WINDOW_SECONDS) -> None:
        self.limit = limit
        self.window = window
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = Lock()

    def _prune(self, key: str, now: float) -> Deque[float]:
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] > self.window:
            hits.popleft()
        return hits

    def retry_after(self, key: str) -> Optional[int]:
        """Seconds until ``key`` may try again, or ``None`` if it is not limited."""
        now = time.monotonic()
        with self._lock:
            hits = self._prune(key, now)
            if len(hits) < self.limit:
                return None
            return max(1, int(self.window - (now - hits[0])))

    def fail(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(key, now).append(now)
            if len(self._hits) > 10_000:  # bound memory under a spray of distinct keys
                for k in [k for k, v in self._hits.items() if not v][:5_000]:
                    del self._hits[k]

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


by_email = FailureLimiter(MAX_FAILURES_PER_EMAIL)
by_client = FailureLimiter(MAX_FAILURES_PER_CLIENT)
