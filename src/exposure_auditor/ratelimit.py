"""Sliding-window rate limiting.

In-process only: good enough for one container and for tests. With more
than one task behind the load balancer, put API Gateway usage plans or a
Redis-backed limiter in front; the per-day scan quota is enforced in the
database and does not depend on this.
"""

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str, limit: int, window_s: float) -> float | None:
        """Record a hit. Returns seconds to wait if over the limit, else None."""
        now = time.monotonic()
        q = self._hits[key]
        while q and q[0] <= now - window_s:
            q.popleft()
        if len(q) >= limit:
            return q[0] + window_s - now
        q.append(now)
        return None
