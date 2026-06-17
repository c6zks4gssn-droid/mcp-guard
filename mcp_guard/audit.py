"""
Audit log for mcp-guard: records every intercepted MCP tool call.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import IO, Literal


Decision = Literal["allowed", "blocked", "rate_limited", "auth_failed"]


@dataclass
class GuardAuditEntry:
    decision: Decision
    agent_id: str
    method: str          # JSON-RPC method, e.g. "tools/call"
    tool_name: str       # e.g. "wallet_request"
    session_id: str
    timestamp: float = field(default_factory=time.time)
    amount_usd: float = 0.0
    vendor: str = ""
    reason: str = ""
    latency_ms: float = 0.0

    def to_json(self) -> str:
        return json.dumps(asdict(self))


class GuardAuditLog:
    """Thread-safe, optionally file-backed audit log."""

    def __init__(self, path: str | None = None) -> None:
        self._entries: list[GuardAuditEntry] = []
        self._lock = threading.Lock()
        self._file: IO | None = open(path, "a", buffering=1) if path else None

    def record(self, entry: GuardAuditEntry) -> None:
        with self._lock:
            self._entries.append(entry)
        if self._file:
            self._file.write(entry.to_json() + "\n")

    def entries_for_agent(self, agent_id: str) -> list[GuardAuditEntry]:
        with self._lock:
            return [e for e in self._entries if e.agent_id == agent_id]

    def all_entries(self) -> list[GuardAuditEntry]:
        with self._lock:
            return list(self._entries)

    def stats(self) -> dict:
        with self._lock:
            total = len(self._entries)
            by_decision: dict[str, int] = {}
            for e in self._entries:
                by_decision[e.decision] = by_decision.get(e.decision, 0) + 1
        return {"total": total, "by_decision": by_decision}

    def close(self) -> None:
        if self._file:
            self._file.close()
            self._file = None
