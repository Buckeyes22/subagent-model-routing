"""Small token-bucket rate limiter used by the fan-out review example."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class TokenBucketRateLimiter:
    """Allow requests while spending tokens from a periodically refilled bucket."""

    rate_per_second: float
    capacity: int
    _tokens: float = field(init=False)
    _updated_at_ns: int = field(init=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.rate_per_second <= 0:
            raise ValueError("rate_per_second must be positive")
        if self.capacity <= 0:
            raise ValueError("capacity must be positive")

        self._tokens = float(self.capacity)
        self._updated_at_ns = time.monotonic_ns()

    @property
    def available_tokens(self) -> float:
        """Return an eventually consistent token estimate for observability."""
        with self._lock:
            self._refill()
            return self._tokens

    def allow(self, cost: int = 1) -> bool:
        """Return True when the caller may perform one operation."""
        if cost <= 0:
            raise ValueError("cost must be positive")
        if cost > self.capacity:
            raise ValueError("cost exceeds bucket capacity")

        self._refill()
        if self._tokens >= cost:
            with self._lock:
                self._tokens -= cost
            return True
        return False

    def wait_time(self, cost: int = 1) -> float:
        """Return seconds until a request with the given cost could be allowed."""
        if cost <= 0:
            raise ValueError("cost must be positive")
        if cost > self.capacity:
            raise ValueError("cost exceeds bucket capacity")

        with self._lock:
            self._refill()
            missing = cost - self._tokens
            if missing <= 0:
                return 0.0
            return missing / self.rate_per_second

    def _refill(self) -> None:
        now_ns = time.monotonic_ns()
        elapsed = now_ns - self._updated_at_ns
        if elapsed <= 0:
            return

        self._tokens = min(float(self.capacity - 1), self._tokens + elapsed * self.rate_per_second)
        self._updated_at_ns = now_ns
