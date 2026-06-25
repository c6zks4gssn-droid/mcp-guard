"""
Persistent SQLite backend for the approval queue (v0.1.3).

Survives restarts. Same interface as ApprovalQueue so it can be swapped.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from .approval import ApprovalQueue, ApprovalRequest, ApprovalStatus


class SQLiteApprovalQueue(ApprovalQueue):
    """Approval queue backed by SQLite — survives restarts."""

    def __init__(self, db_path: str = ":memory:", ttl_seconds: int = 300) -> None:
        super().__init__(ttl_seconds)
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS approvals (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                amount_usd REAL NOT NULL,
                session_id TEXT NOT NULL,
                created_at REAL NOT NULL,
                decided_at REAL,
                status TEXT NOT NULL,
                decided_by TEXT,
                reason TEXT DEFAULT ''
            )
        """)
        self._db.commit()
        self._load_pending()

    def _load_pending(self) -> None:
        """Load all requests (pending + recently decided) from DB on startup."""
        rows = self._db.execute("SELECT * FROM approvals").fetchall()
        for r in rows:
            req = ApprovalRequest(
                id=r["id"],
                agent_id=r["agent_id"],
                tool_name=r["tool_name"],
                amount_usd=r["amount_usd"],
                session_id=r["session_id"],
                created_at=r["created_at"],
                decided_at=r["decided_at"],
                status=ApprovalStatus(r["status"]),
                decided_by=r["decided_by"],
                reason=r["reason"] or "",
            )
            if req.status == ApprovalStatus.PENDING:
                self._pending[req.id] = req
            else:
                self._decided[req.id] = req

    def request(
        self,
        agent_id: str,
        tool_name: str,
        amount_usd: float = 0.0,
        session_id: str = "",
    ) -> ApprovalRequest:
        req = super().request(agent_id, tool_name, amount_usd, session_id)
        self._db.execute(
            """INSERT INTO approvals
               (id, agent_id, tool_name, amount_usd, session_id, created_at, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (req.id, req.agent_id, req.tool_name, req.amount_usd,
             req.session_id, req.created_at, req.status.value),
        )
        self._db.commit()
        return req

    def approve(self, req_id: str, decided_by: str = "admin") -> ApprovalRequest | None:
        req = super().approve(req_id, decided_by)
        if req:
            self._db.execute(
                """UPDATE approvals
                   SET status=?, decided_at=?, decided_by=?
                   WHERE id=?""",
                (req.status.value, req.decided_at, req.decided_by, req_id),
            )
            self._db.commit()
        return req

    def deny(
        self, req_id: str, decided_by: str = "admin", reason: str = ""
    ) -> ApprovalRequest | None:
        req = super().deny(req_id, decided_by, reason)
        if req:
            self._db.execute(
                """UPDATE approvals
                   SET status=?, decided_at=?, decided_by=?, reason=?
                   WHERE id=?""",
                (req.status.value, req.decided_at, req.decided_by, req.reason, req_id),
            )
            self._db.commit()
        return req

    def _expire_stale(self) -> None:
        """Expire pending requests older than TTL — persists the change."""
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
            self._db.execute(
                """UPDATE approvals
                   SET status=?, decided_at=?
                   WHERE id=?""",
                (req.status.value, req.decided_at, rid),
            )
        if expired:
            self._db.commit()

    def close(self) -> None:
        """Close the DB connection."""
        self._db.close()