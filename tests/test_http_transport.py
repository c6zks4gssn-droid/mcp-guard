"""Tests for HTTP/SSE transport."""

import json
import pytest
import threading
import time
import urllib.request
from mcp_guard.config import GuardConfig, AuthConfig, PolicyConfig
from mcp_guard.http_transport import GuardHTTPServer, run_http_server
from mcp_guard.proxy import MCPProxy


@pytest.fixture
def http_server():
    """Start a test HTTP server on a random port."""
    proxy = MCPProxy(
        policy=PolicyConfig(max_spend_per_session=100.0),
    )
    proxy._metrics = {
        "requests_total": 0,
        "blocked_total": 0,
        "allowed_total": 0,
        "spend_total": 0.0,
    }

    # Wrap intercept for metrics
    _orig = proxy.intercept
    def _counting(raw, session_id=None, http_headers=None):
        proxy._metrics["requests_total"] += 1
        result = _orig(raw, session_id, http_headers)
        if result.allowed:
            proxy._metrics["allowed_total"] += 1
        else:
            proxy._metrics["blocked_total"] += 1
        return result
    proxy.intercept = _counting

    server = GuardHTTPServer(("127.0.0.1", 0), proxy, ["echo", "test"], {})
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.1)
    yield server, port
    server.shutdown()


class TestHTTPEndpoints:
    def test_health_check(self, http_server):
        server, port = http_server
        resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/health")
        assert resp.status == 200
        data = json.loads(resp.read())
        assert data["status"] == "ok"
        assert "version" in data

    def test_404_unknown_path(self, http_server):
        server, port = http_server
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/unknown")
            assert False, "should 404"
        except urllib.error.HTTPError as e:
            assert e.code == 404

    def test_rpc_unauthorized_no_auth(self, http_server):
        server, port = http_server
        # No auth configured — should pass auth, but backend (echo) fails gracefully
        body = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {},
        }).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/rpc",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req)
        data = json.loads(resp.read())
        # Should get a JSON-RPC response (allowed, backend may fail)
        assert "jsonrpc" in data

    def test_rpc_blocked_by_auth(self):
        """Test that auth blocks unauthorized requests over HTTP."""
        proxy = MCPProxy(
            policy=PolicyConfig(),
        )
        from mcp_guard.auth import ApiKeyAuth
        proxy.auth = ApiKeyAuth(["sk-test-123"])

        proxy._metrics = {
            "requests_total": 0,
            "blocked_total": 0,
            "allowed_total": 0,
            "spend_total": 0.0,
        }

        server = GuardHTTPServer(("127.0.0.1", 0), proxy, ["echo"], {})
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        time.sleep(0.1)

        try:
            body = json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "test", "arguments": {}},
            }).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/rpc",
                data=body,
                headers={"Content-Type": "application/json"},
            )
            resp = urllib.request.urlopen(req)
            data = json.loads(resp.read())
            assert "error" in data
            assert data["error"]["code"] == -32001
        finally:
            server.shutdown()

    def test_metrics_endpoint(self, http_server):
        server, port = http_server
        # Make a request first
        body = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {},
        }).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/rpc",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req)
        except Exception:
            pass

        resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics")
        assert resp.status == 200
        text = resp.read().decode()
        assert "mcp_guard_requests_total" in text
        assert "mcp_guard_blocked_total" in text

    def test_rpc_with_api_key_header(self):
        """Test that API key in header authenticates over HTTP."""
        proxy = MCPProxy(
            policy=PolicyConfig(),
        )
        from mcp_guard.auth import ApiKeyAuth
        proxy.auth = ApiKeyAuth(["sk-test-123"])

        proxy._metrics = {
            "requests_total": 0,
            "blocked_total": 0,
            "allowed_total": 0,
            "spend_total": 0.0,
        }

        server = GuardHTTPServer(("127.0.0.1", 0), proxy, ["echo"], {})
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        time.sleep(0.1)

        try:
            body = json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            }).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/rpc",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-API-Key": "sk-test-123",
                },
            )
            resp = urllib.request.urlopen(req)
            data = json.loads(resp.read())
            # Should pass auth (backend may fail but no auth error)
            assert data.get("error", {}).get("code") != -32001
        finally:
            server.shutdown()