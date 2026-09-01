from __future__ import annotations

import logging
import time
from collections import deque
from threading import Lock

log = logging.getLogger(__name__)


class SlidingWindowLimit:
    """In-memory sliding-window rate limiter.

    Limits actions per key within a window. Thread-safe for single-process use.
    For multi-process: switch to Redis (out of scope for MVP).
    """

    def __init__(self, *, max_actions: int, window_seconds: float) -> None:
        self._max = max_actions
        self._window = window_seconds
        self._events: dict[str, deque[float]] = {}
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        cutoff = now - self._window
        with self._lock:
            q = self._events.setdefault(key, deque())
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= self._max:
                return False
            q.append(now)
            return True

    def remaining(self, key: str) -> int:
        with self._lock:
            q = self._events.get(key) or deque()
            return max(0, self._max - len(q))


rotate_key_limiter = SlidingWindowLimit(max_actions=5, window_seconds=24 * 3600)
