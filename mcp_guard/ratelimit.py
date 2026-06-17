"""
Per-agent rate limiting for mcp-guard.

Uses a sliding window counter — no external dependencies.
"""

from __future__ import annotations

import collections
import threading
import time
from dataclasses import dataclass


@dataclass
class RateLimitResult:
    allowed: bool
    agent_id: str
    requests_in_window: int
    limit: int
    retry_after_seconds: float = 0.0
    reason: str = ""


class RateLimiter:
    """
    Token-bucket rate limiter, per agent.

    Args:
        requests_per_minute: Max requests per agent per 60s window. 0 = unlimited.
        spend_per_hour_usd:  Max spend per agent per 3600s window. 0 = unlimited.
    """

    def __init__(
        self,
        requests_per_minute: int = 0,
        spend_per_hour_usd: float = 0.0,
    ) -> None:
        self.rpm = requests_per_minute
        self.sph = spend_per_hour_usd
        # deque of timestamps per agent (requests)
        self._req_windows: dict[str, collections.deque] = collections.defaultdict(
            lambda: collections.deque()
        )
        # deque of (timestamp, usd) per agent (spend)
        self._spend_windows: dict[str, collections.deque] = collections.defaultdict(
            lambda: collections.deque()
        )
        self._lock = threading.Lock()

    def check_request(self, agent_id: str) -> RateLimitResult:
        if not self.rpm:
            return RateLimitResult(allowed=True, agent_id=agent_id, requests_in_window=0, limit=0)

        now = time.time()
        window_start = now - 60.0

        with self._lock:
            dq = self._req_windows[agent_id]
            # Evict old entries
            while dq and dq[0] < window_start:
                dq.popleft()
            count = len(dq)
            if count >= self.rpm:
                oldest = dq[0]
                retry_after = oldest + 60.0 - now
                return RateLimitResult(
                    allowed=False,
                    agent_id=agent_id,
                    requests_in_window=count,
                    limit=self.rpm,
                    retry_after_seconds=max(0.0, retry_after),
                    reason=f"rate limit: {count}/{self.rpm} requests/min",
                )
            dq.append(now)

        return RateLimitResult(
            allowed=True, agent_id=agent_id,
            requests_in_window=count + 1, limit=self.rpm,
        )

    def check_spend(self, agent_id: str, amount_usd: float) -> RateLimitResult:
        if not self.sph:
            return RateLimitResult(allowed=True, agent_id=agent_id, requests_in_window=0, limit=0)

        now = time.time()
        window_start = now - 3600.0

        with self._lock:
            dq = self._spend_windows[agent_id]
            while dq and dq[0][0] < window_start:
                dq.popleft()
            spent = sum(e[1] for e in dq)
            if spent + amount_usd > self.sph:
                return RateLimitResult(
                    allowed=False,
                    agent_id=agent_id,
                    requests_in_window=int(spent * 100),
                    limit=int(self.sph * 100),
                    reason=f"spend limit: ${spent:.4f}+${amount_usd:.4f} > ${self.sph:.2f}/hr",
                )
            dq.append((now, amount_usd))

        return RateLimitResult(allowed=True, agent_id=agent_id, requests_in_window=0, limit=0)

    def record_spend(self, agent_id: str, amount_usd: float) -> None:
        """Record spend after a payment completes (when using manual tracking)."""
        now = time.time()
        with self._lock:
            self._spend_windows[agent_id].append((now, amount_usd))

    def reset(self, agent_id: str) -> None:
        with self._lock:
            self._req_windows.pop(agent_id, None)
            self._spend_windows.pop(agent_id, None)
