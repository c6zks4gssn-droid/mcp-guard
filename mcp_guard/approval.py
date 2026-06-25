"""
Approval queue for mcp-guard v0.1.2.

When a tool call exceeds the `require_approval_above` threshold,
it's held in a pending queue until a human approves or denies it.

Usage:
    from mcp_guard.approval import ApprovalQueue
    queue = ApprovalQueue()
    req = queue.request(agent_id="agent-1", tool="wallet_pay", amount=5.00)
    # req.status == "pending"
    queue.approve(req.id)   # → "approved"
    queue.deny(req.id)      # → "denied"
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


@dataclass
class ApprovalRequest:
    id: str
    agent_id: str
    tool_name: str
    amount_usd: float
    session_id: str
    created_at: float = field(default_factory=time.time)
    decided_at: float | None = None
    status: ApprovalStatus = ApprovalStatus.PENDING
    decided_by: str | None = None
    reason: str = ""


class ApprovalQueue:
    """In-memory approval queue. Persistent backend (Redis, SQLite) planned."""

    def __init__(self, ttl_seconds: int = 300) -> None:
        self._pending: dict[str, ApprovalRequest] = {}
        self._decided: dict[str, ApprovalRequest] = {}
        self._ttl = ttl_seconds

    def request(
        self,
        agent_id: str,
        tool_name: str,
        amount_usd: float = 0.0,
        session_id: str = "",
    ) -> ApprovalRequest:
        """Submit a new approval request. Returns the request with status=pending."""
        req = ApprovalRequest(
            id=str(uuid.uuid4()),
            agent_id=agent_id,
            tool_name=tool_name,
            amount_usd=amount_usd,
            session_id=session_id,
        )
        self._pending[req.id] = req
        return req

    def approve(self, req_id: str, decided_by: str = "admin") -> ApprovalRequest | None:
        """Approve a pending request."""
        req = self._pending.pop(req_id, None)
        if req is None:
            return None
        req.status = ApprovalStatus.APPROVED
        req.decided_at = time.time()
        req.decided_by = decided_by
        self._decided[req_id] = req
        return req

    def deny(self, req_id: str, decided_by: str = "admin", reason: str = "") -> ApprovalRequest | None:
        """Deny a pending request."""
        req = self._pending.pop(req_id, None)
        if req is None:
            return None
        req.status = ApprovalStatus.DENIED
        req.decided_at = time.time()
        req.decided_by = decided_by
        req.reason = reason
        self._decided[req_id] = req
        return req

    def get(self, req_id: str) -> ApprovalRequest | None:
        """Get any request by ID (pending or decided)."""
        return self._pending.get(req_id) or self._decided.get(req_id)

    def list_pending(self) -> list[ApprovalRequest]:
        """List all pending requests, expiring stale ones."""
        self._expire_stale()
        return list(self._pending.values())

    def list_decided(self, limit: int = 50) -> list[ApprovalRequest]:
        """List recently decided requests."""
        items = sorted(self._decided.values(), key=lambda r: r.decided_at or 0, reverse=True)
        return items[:limit]

    def _expire_stale(self) -> None:
        """Expire pending requests older than TTL."""
        now = time.time()
        expired = [
            rid for rid, req in self._pending.items()
            if now - req.created_at > self._ttl
        ]
        for rid in expired:
            req = self._pending.pop(rid)
            req.status = ApprovalStatus.EXPIRED
            req.decided_at = now
            self._decided[rid] = req