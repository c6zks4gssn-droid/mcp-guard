"""Tests for v0.1.2 features: tool allowlist/denylist and approval queue."""

import json
import pytest
from mcp_guard.config import GuardConfig, PolicyConfig
from mcp_guard.proxy import MCPProxy
from mcp_guard.approval import ApprovalQueue, ApprovalStatus


def _tools_call(tool: str, args: dict | None = None) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": args or {}},
    }


class TestToolAllowlist:
    def test_allowed_tool_passes(self):
        proxy = MCPProxy(
            policy=PolicyConfig(tool_allowlist=["filesystem_read", "search"]),
        )
        result = proxy.intercept(_tools_call("filesystem_read"))
        assert result.allowed

    def test_blocked_tool_not_on_allowlist(self):
        proxy = MCPProxy(
            policy=PolicyConfig(tool_allowlist=["filesystem_read"]),
        )
        result = proxy.intercept(_tools_call("wallet_pay"))
        assert not result.allowed
        assert "not on allowlist" in result.block_reason
        assert result.error_response["error"]["code"] == -32003

    def test_denylist_blocks_tool(self):
        proxy = MCPProxy(
            policy=PolicyConfig(tool_denylist=["dangerous_tool"]),
        )
        result = proxy.intercept(_tools_call("dangerous_tool"))
        assert not result.allowed
        assert "denylist" in result.block_reason
        assert result.error_response["error"]["code"] == -32003

    def test_no_list_allows_all(self):
        proxy = MCPProxy(policy=PolicyConfig())
        result = proxy.intercept(_tools_call("any_tool"))
        assert result.allowed

    def test_allowlist_takes_precedence_over_denylist(self):
        proxy = MCPProxy(
            policy=PolicyConfig(tool_allowlist=["safe"], tool_denylist=["safe"]),
        )
        result = proxy.intercept(_tools_call("safe"))
        assert not result.allowed  # denylist wins


class TestApprovalQueue:
    def test_request_starts_pending(self):
        queue = ApprovalQueue()
        req = queue.request("agent-1", "wallet_pay", 5.00)
        assert req.status == ApprovalStatus.PENDING
        assert req.amount_usd == 5.00

    def test_approve_changes_status(self):
        queue = ApprovalQueue()
        req = queue.request("agent-1", "wallet_pay", 5.00)
        approved = queue.approve(req.id)
        assert approved is not None
        assert approved.status == ApprovalStatus.APPROVED
        assert approved.decided_by == "admin"

    def test_deny_changes_status(self):
        queue = ApprovalQueue()
        req = queue.request("agent-1", "wallet_pay", 5.00)
        denied = queue.deny(req.id, reason="too expensive")
        assert denied is not None
        assert denied.status == ApprovalStatus.DENIED
        assert denied.reason == "too expensive"

    def test_list_pending(self):
        queue = ApprovalQueue()
        queue.request("agent-1", "wallet_pay", 5.00)
        queue.request("agent-2", "wallet_pay", 10.00)
        pending = queue.list_pending()
        assert len(pending) == 2

    def test_expired_requests(self):
        queue = ApprovalQueue(ttl_seconds=0)
        req = queue.request("agent-1", "wallet_pay", 5.00)
        import time
        time.sleep(0.1)
        pending = queue.list_pending()
        assert len(pending) == 0
        decided = queue.list_decided()
        assert any(r.id == req.id and r.status == ApprovalStatus.EXPIRED for r in decided)

    def test_get_returns_none_for_unknown(self):
        queue = ApprovalQueue()
        assert queue.get("nonexistent") is None

    def test_approve_returns_none_for_unknown(self):
        queue = ApprovalQueue()
        assert queue.approve("nonexistent") is None