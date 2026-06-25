"""
MCPProxy: the core JSON-RPC intercept engine.

Sits between an MCP client (Claude Desktop, Cursor, etc.) and one or more
backend MCP servers. Reads JSON-RPC messages from stdin/socket, applies
auth + rate limiting + spending policy, then forwards to the backend.

Transport: STDIO (default) or HTTP/SSE (future).

Message flow:
    Client → [MCPProxy.handle(msg)] → Backend MCP server
                    ↓
              Auth check
              Rate limit check
              Spending policy check (for wallet_* tools)
              Audit log
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .auth import AuthProvider, AuthResult, NoAuth
from .audit import GuardAuditLog, GuardAuditEntry
from .ratelimit import RateLimiter
from .config import GuardConfig, PolicyConfig

# Tool names that involve spending — these get extra policy checks
SPENDING_TOOLS = {
    "wallet_request", "wallet_approve", "pay_create_checkout",
    "wallet_pay", "x402_pay",
}


@dataclass
class MCPMessage:
    """Parsed JSON-RPC 2.0 message."""
    raw: dict
    id: Any = None
    method: str = ""
    params: dict = field(default_factory=dict)
    is_notification: bool = False

    @classmethod
    def parse(cls, raw: dict) -> "MCPMessage":
        return cls(
            raw=raw,
            id=raw.get("id"),
            method=raw.get("method", ""),
            params=raw.get("params") or {},
            is_notification="id" not in raw,
        )


@dataclass
class InterceptResult:
    """Result of the proxy's policy check on a message."""
    allowed: bool
    agent_id: str = "anonymous"
    session_id: str = ""
    tool_name: str = ""
    amount_usd: float = 0.0
    block_reason: str = ""
    error_response: dict | None = None   # JSON-RPC error to send back to client


class MCPProxy:
    """
    Stateless (per-message) policy enforcer.

    Usage:
        proxy = MCPProxy.from_config(guard_config)

        # For each incoming JSON-RPC message:
        raw = json.loads(stdin.readline())
        result = proxy.intercept(raw, session_id="sess-abc")
        if not result.allowed:
            print(json.dumps(result.error_response))
        else:
            # Forward raw to backend MCP server
            forward_to_backend(raw)
    """

    def __init__(
        self,
        auth: AuthProvider | None = None,
        rate_limiter: RateLimiter | None = None,
        policy: PolicyConfig | None = None,
        audit_log: GuardAuditLog | None = None,
        session_spend: dict | None = None,  # agent_id -> float
    ) -> None:
        self.auth = auth or NoAuth()
        self.rate_limiter = rate_limiter or RateLimiter()
        self.policy = policy or PolicyConfig()
        self.audit_log = audit_log or GuardAuditLog()
        self._session_spend: dict[str, float] = session_spend or {}

    @classmethod
    def from_config(cls, config: GuardConfig) -> "MCPProxy":
        from .auth import build_auth_provider
        return cls(
            auth=build_auth_provider(config.auth),
            rate_limiter=RateLimiter(
                requests_per_minute=config.policies.rate_limit.requests_per_minute,
                spend_per_hour_usd=config.policies.rate_limit.spend_per_hour_usd,
            ),
            policy=config.policies,
            audit_log=GuardAuditLog(path=config.policies.audit_log),
        )

    def intercept(
        self,
        raw: dict,
        session_id: str | None = None,
        http_headers: dict | None = None,
    ) -> InterceptResult:
        """
        Evaluate a JSON-RPC message against all policies.
        Returns InterceptResult — check .allowed before forwarding.
        """
        t0 = time.monotonic()
        msg = MCPMessage.parse(raw)
        session_id = session_id or str(uuid.uuid4())[:8]

        # --- 1. Authentication ---
        credentials = self._extract_credentials(msg, http_headers or {})
        auth_result = self.auth.verify(credentials)
        if not auth_result.success:
            entry = GuardAuditEntry(
                decision="auth_failed",
                agent_id="unknown",
                method=msg.method,
                tool_name=_tool_name(msg),
                session_id=session_id,
                reason=auth_result.error,
                latency_ms=(time.monotonic() - t0) * 1000,
            )
            self.audit_log.record(entry)
            return InterceptResult(
                allowed=False,
                agent_id="unknown",
                session_id=session_id,
                block_reason=auth_result.error,
                error_response=_rpc_error(msg.id, -32001, f"Unauthorized: {auth_result.error}"),
            )

        agent_id = auth_result.agent_id

        # --- 2. Rate limiting ---
        rl = self.rate_limiter.check_request(agent_id)
        if not rl.allowed:
            entry = GuardAuditEntry(
                decision="rate_limited",
                agent_id=agent_id,
                method=msg.method,
                tool_name=_tool_name(msg),
                session_id=session_id,
                reason=rl.reason,
                latency_ms=(time.monotonic() - t0) * 1000,
            )
            self.audit_log.record(entry)
            return InterceptResult(
                allowed=False,
                agent_id=agent_id,
                session_id=session_id,
                block_reason=rl.reason,
                error_response=_rpc_error(
                    msg.id, -32029,
                    f"Rate limited: {rl.reason}",
                    {"retry_after": rl.retry_after_seconds},
                ),
            )

        # --- 3. Tool allowlist/denylist (v0.1.2) ---
        tool_name = _tool_name(msg)
        if tool_name and msg.method == "tools/call":
            if self.policy.tool_denylist and tool_name in self.policy.tool_denylist:
                entry = GuardAuditEntry(
                    decision="blocked",
                    agent_id=agent_id,
                    method=msg.method,
                    tool_name=tool_name,
                    session_id=session_id,
                    reason=f"tool '{tool_name}' is on denylist",
                    latency_ms=(time.monotonic() - t0) * 1000,
                )
                self.audit_log.record(entry)
                return InterceptResult(
                    allowed=False,
                    agent_id=agent_id,
                    session_id=session_id,
                    tool_name=tool_name,
                    block_reason=f"tool '{tool_name}' is on denylist",
                    error_response=_rpc_error(msg.id, -32003, f"Tool blocked: '{tool_name}' is on denylist"),
                )
            if self.policy.tool_allowlist and tool_name not in self.policy.tool_allowlist:
                entry = GuardAuditEntry(
                    decision="blocked",
                    agent_id=agent_id,
                    method=msg.method,
                    tool_name=tool_name,
                    session_id=session_id,
                    reason=f"tool '{tool_name}' not on allowlist",
                    latency_ms=(time.monotonic() - t0) * 1000,
                )
                self.audit_log.record(entry)
                return InterceptResult(
                    allowed=False,
                    agent_id=agent_id,
                    session_id=session_id,
                    tool_name=tool_name,
                    block_reason=f"tool '{tool_name}' not on allowlist",
                    error_response=_rpc_error(msg.id, -32003, f"Tool blocked: '{tool_name}' not on allowlist"),
                )

        # --- 4. Spending policy (only for spending tool calls) ---
        tool_name = _tool_name(msg)
        amount_usd = 0.0
        if tool_name in SPENDING_TOOLS and msg.method == "tools/call":
            amount_usd = float(msg.params.get("arguments", {}).get("amount", 0.0))
            block = self._check_spend_policy(agent_id, session_id, amount_usd, tool_name)
            if block:
                entry = GuardAuditEntry(
                    decision="blocked",
                    agent_id=agent_id,
                    method=msg.method,
                    tool_name=tool_name,
                    session_id=session_id,
                    amount_usd=amount_usd,
                    reason=block,
                    latency_ms=(time.monotonic() - t0) * 1000,
                )
                self.audit_log.record(entry)
                return InterceptResult(
                    allowed=False,
                    agent_id=agent_id,
                    session_id=session_id,
                    tool_name=tool_name,
                    amount_usd=amount_usd,
                    block_reason=block,
                    error_response=_rpc_error(msg.id, -32002, f"Payment blocked: {block}"),
                )
            # Record spend
            spend_key = f"{agent_id}:{session_id}"
            self._session_spend[spend_key] = (
                self._session_spend.get(spend_key, 0.0) + amount_usd
            )

        # --- 5. Allow ---
        entry = GuardAuditEntry(
            decision="allowed",
            agent_id=agent_id,
            method=msg.method,
            tool_name=tool_name,
            session_id=session_id,
            amount_usd=amount_usd,
            latency_ms=(time.monotonic() - t0) * 1000,
        )
        self.audit_log.record(entry)
        return InterceptResult(
            allowed=True,
            agent_id=agent_id,
            session_id=session_id,
            tool_name=tool_name,
            amount_usd=amount_usd,
        )

    def _check_spend_policy(
        self, agent_id: str, session_id: str, amount_usd: float, tool_name: str
    ) -> str:
        """Return a block reason string, or empty string if allowed."""
        spend_key = f"{agent_id}:{session_id}"
        session_spent = self._session_spend.get(spend_key, 0.0)
        budget = self.policy.max_spend_per_session

        if budget != float("inf") and session_spent + amount_usd > budget:
            return (
                f"would exceed session budget ${budget:.2f} "
                f"(spent ${session_spent:.4f} + ${amount_usd:.4f})"
            )

        rl = self.rate_limiter.check_spend(agent_id, amount_usd)
        if not rl.allowed:
            return rl.reason

        return ""

    @staticmethod
    def _extract_credentials(msg: MCPMessage, headers: dict) -> dict:
        """Pull auth credentials from message meta or HTTP headers."""
        creds: dict = {}
        # From JSON-RPC params._meta
        meta = msg.params.get("_meta", {})
        if "api_key" in meta:
            creds["api_key"] = meta["api_key"]
        if "token" in meta:
            creds["token"] = meta["token"]
        # From HTTP headers
        if "authorization" in headers:
            creds["authorization"] = headers["authorization"]
        if "x-api-key" in headers:
            creds["api_key"] = headers["x-api-key"]
        return creds


def _tool_name(msg: MCPMessage) -> str:
    if msg.method == "tools/call":
        return msg.params.get("name", "")
    return ""


def _rpc_error(id: Any, code: int, message: str, data: dict | None = None) -> dict:
    err: dict = {"code": code, "message": message}
    if data:
        err["data"] = data
    return {
        "jsonrpc": "2.0",
        "id": id,
        "error": err,
    }
