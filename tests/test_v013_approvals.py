"""Tests for v0.1.3: persistent approval queue + CLI + proxy integration."""

import json
import os
import tempfile
import time
import pytest
from mcp_guard.approval import ApprovalStatus
from mcp_guard.approval_store import SQLiteApprovalQueue
from mcp_guard.approvals_cli import cmd_approvals_list, cmd_approvals_approve, cmd_approvals_deny
from mcp_guard.proxy import MCPProxy
from mcp_guard.config import PolicyConfig, AuthConfig


@pytest.fixture
def temp_db():
    """Create a temp SQLite DB path."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


class TestSQLiteApprovalQueue:
    def test_persistence_across_restarts(self, temp_db):
        """Survives a queue restart — pending stays in DB."""
        q1 = SQLiteApprovalQueue(db_path=temp_db, ttl_seconds=300)
        req = q1.request("agent-1", "wallet_pay", 5.00)
        q1.close()

        # Restart
        q2 = SQLiteApprovalQueue(db_path=temp_db, ttl_seconds=300)
        try:
            assert req.id in q2._pending
            assert q2._pending[req.id].amount_usd == 5.00
        finally:
            q2.close()

    def test_approve_persists(self, temp_db):
        q1 = SQLiteApprovalQueue(db_path=temp_db)
        req = q1.request("agent-1", "wallet_pay", 5.00)
        q1.approve(req.id)
        q1.close()

        q2 = SQLiteApprovalQueue(db_path=temp_db)
        try:
            assert req.id not in q2._pending
            assert q2._decided[req.id].status == ApprovalStatus.APPROVED
        finally:
            q2.close()

    def test_deny_with_reason(self, temp_db):
        q = SQLiteApprovalQueue(db_path=temp_db)
        req = q.request("agent-1", "wallet_pay", 5.00)
        q.deny(req.id, reason="too expensive")
        assert q._decided[req.id].reason == "too expensive"

    def test_in_memory_mode(self):
        q = SQLiteApprovalQueue(db_path=":memory:")
        req = q.request("agent-1", "wallet_pay", 5.00)
        assert req in q.list_pending()


class TestCLI:
    def test_list_pending(self, temp_db, capsys):
        q = SQLiteApprovalQueue(db_path=temp_db)
        q.request("agent-1", "wallet_pay", 5.00)
        q.request("agent-2", "wallet_pay", 10.00)
        q.close()

        cmd_approvals_list(temp_db, show_decided=False)
        captured = capsys.readouterr()
        assert "PENDING (2)" in captured.out
        assert "agent-1" in captured.out
        assert "agent-2" in captured.out

    def test_list_empty(self, temp_db, capsys):
        cmd_approvals_list(temp_db, show_decided=False)
        captured = capsys.readouterr()
        assert "No pending" in captured.out

    def test_approve_via_cli(self, temp_db, capsys):
        q = SQLiteApprovalQueue(db_path=temp_db)
        req = q.request("agent-1", "wallet_pay", 5.00)
        q.close()

        cmd_approvals_approve(temp_db, req.id[:8], decided_by="tester")
        captured = capsys.readouterr()
        assert "Approved" in captured.out

    def test_deny_via_cli(self, temp_db, capsys):
        q = SQLiteApprovalQueue(db_path=temp_db)
        req = q.request("agent-1", "wallet_pay", 5.00)
        q.close()

        cmd_approvals_deny(temp_db, req.id[:8], decided_by="tester", reason="nope")
        captured = capsys.readouterr()
        assert "Denied" in captured.out
        assert "nope" in captured.out

    def test_approve_nonexistent_returns_1(self, temp_db, capsys):
        result = cmd_approvals_approve(temp_db, "nonexistent", decided_by="tester")
        assert result == 1


class TestProxyApprovalHold:
    def _tools_call(self, tool: str, amount: float = 0.0):
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": {"amount": amount}},
        }

    def test_spending_below_threshold_allowed(self, temp_db):
        queue = SQLiteApprovalQueue(db_path=temp_db)
        try:
            proxy = MCPProxy(
                policy=PolicyConfig(
                    max_spend_per_session=100.0,
                    require_approval_above=10.0,
                ),
                approval_queue=queue,
            )
            result = proxy.intercept(self._tools_call("wallet_pay", amount=5.0))
            assert result.allowed
            assert len(queue.list_pending()) == 0
        finally:
            queue.close()

    def test_spending_above_threshold_held(self, temp_db):
        queue = SQLiteApprovalQueue(db_path=temp_db)
        try:
            proxy = MCPProxy(
                policy=PolicyConfig(
                    max_spend_per_session=100.0,
                    require_approval_above=5.0,
                ),
                approval_queue=queue,
            )
            result = proxy.intercept(self._tools_call("wallet_pay", amount=10.0))
            assert not result.allowed
            assert "approval" in result.block_reason.lower()
            assert result.error_response["error"]["code"] == -32004
            assert "approval_id" in result.error_response["error"]["data"]

            # Should be in queue
            pending = queue.list_pending()
            assert len(pending) == 1
            assert pending[0].amount_usd == 10.0
        finally:
            queue.close()

    def test_held_request_appears_in_db(self, temp_db):
        queue = SQLiteApprovalQueue(db_path=temp_db)
        try:
            proxy = MCPProxy(
                policy=PolicyConfig(
                    max_spend_per_session=100.0,
                    require_approval_above=5.0,
                ),
                approval_queue=queue,
            )
            proxy.intercept(self._tools_call("wallet_pay", amount=10.0))
            req_id = list(queue._pending.keys())[0]
        finally:
            queue.close()

        # Restart queue, check persistence
        queue2 = SQLiteApprovalQueue(db_path=temp_db)
        try:
            assert req_id in queue2._pending
        finally:
            queue2.close()

    def test_no_approval_queue_skips_hold(self):
        """Without an approval_queue attached, no hold happens."""
        proxy = MCPProxy(
            policy=PolicyConfig(
                max_spend_per_session=100.0,
                require_approval_above=5.0,
            ),
            approval_queue=None,
        )
        result = proxy.intercept(self._tools_call("wallet_pay", amount=10.0))
        # No queue → no hold → allowed (assuming budget OK)
        assert result.allowed