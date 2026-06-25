"""
HTTP/SSE transport for mcp-guard v0.1.2.

Exposes the gateway over HTTP so remote MCP clients can connect
without stdio. Uses Server-Sent Events for streaming responses.

Endpoints:
  POST /rpc          — JSON-RPC request → JSON-RPC response
  GET  /sse          — SSE stream for notifications
  GET  /health       — health check
  GET  /metrics      — Prometheus metrics (if enabled)

Run:
  mcp-guard serve-http --config mcp-guard.yaml --port 8080
"""

from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any

from .config import GuardConfig
from .proxy import MCPProxy, InterceptResult


class GuardHTTPHandler(BaseHTTPRequestHandler):
    """HTTP handler for mcp-guard."""

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(200, {"status": "ok", "version": "0.1.2"})
        elif self.path == "/metrics":
            self._prometheus()
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/rpc":
            self._json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"

        try:
            raw = json.loads(body)
        except json.JSONDecodeError:
            self._json(200, {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            })
            return

        headers = {k.lower(): v for k, v in self.headers.items()}
        session_id = headers.get("x-mcp-session", str(uuid.uuid4())[:12])

        result: InterceptResult = self.server.proxy.intercept(
            raw,
            session_id=session_id,
            http_headers=headers,
        )

        if not result.allowed and result.error_response:
            self._json(200, result.error_response)
            return

        # Forward to backend MCP server
        response = self.server._forward_to_backend(raw, self.server)
        self._json(200, response)

    def _json(self, code: int, data: dict) -> None:
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _prometheus(self) -> None:
        proxy = self.server.proxy
        metrics = []
        metrics.append(f"# TYPE mcp_guard_requests_total counter")
        metrics.append(f'mcp_guard_requests_total {proxy._metrics["requests_total"]}')
        metrics.append(f"# TYPE mcp_guard_blocked_total counter")
        metrics.append(f'mcp_guard_blocked_total {proxy._metrics["blocked_total"]}')
        metrics.append(f"# TYPE mcp_guard_allowed_total counter")
        metrics.append(f'mcp_guard_allowed_total {proxy._metrics["allowed_total"]}')
        metrics.append(f"# TYPE mcp_guard_spend_total counter")
        metrics.append(f'mcp_guard_spend_total {proxy._metrics["spend_total"]}')
        body = "\n".join(metrics) + "\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress default logging — audit log handles it
        pass


class GuardHTTPServer(HTTPServer):
    """HTTP server with mcp-guard proxy attached."""

    proxy: MCPProxy
    backend_command: list[str]
    backend_env: dict[str, str]

    def __init__(self, addr: tuple[str, int], proxy: MCPProxy, backend: list[str], env: dict) -> None:
        super().__init__(addr, GuardHTTPHandler)
        self.proxy = proxy
        self.backend_command = backend
        self.backend_env = env

    def _forward_to_backend(self, raw: dict, server: "GuardHTTPServer") -> dict:
        """Forward a JSON-RPC message to the backend MCP server and return response."""
        import subprocess as sp

        try:
            proc = sp.Popen(
                server.backend_command,
                stdin=sp.PIPE,
                stdout=sp.PIPE,
                stderr=sp.PIPE,
                env={**__import__("os").environ, **server.backend_env},
                text=True,
            )
            proc.stdin.write(json.dumps(raw) + "\n")
            proc.stdin.flush()
            proc.stdin.close()
            out = proc.stdout.readline()
            proc.terminate()
            if out:
                return json.loads(out)
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": raw.get("id"),
                "error": {"code": -32603, "message": f"Backend error: {e}"},
            }
        return {
            "jsonrpc": "2.0",
            "id": raw.get("id"),
            "error": {"code": -32603, "message": "No response from backend"},
        }


def run_http_server(
    config: GuardConfig,
    host: str = "0.0.0.0",
    port: int = 8080,
    server_name: str | None = None,
) -> int:
    """Start the HTTP/SSE gateway server."""
    proxy = MCPProxy.from_config(config)

    # Add metrics tracking to proxy
    proxy._metrics = {
        "requests_total": 0,
        "blocked_total": 0,
        "allowed_total": 0,
        "spend_total": 0.0,
    }

    # Wrap intercept to count metrics
    _original_intercept = proxy.intercept

    def _counting_intercept(raw: dict, session_id: str | None = None, http_headers: dict | None = None) -> InterceptResult:
        proxy._metrics["requests_total"] += 1
        result = _original_intercept(raw, session_id, http_headers)
        if result.allowed:
            proxy._metrics["allowed_total"] += 1
            proxy._metrics["spend_total"] += result.amount_usd
        else:
            proxy._metrics["blocked_total"] += 1
        return result

    proxy.intercept = _counting_intercept

    chosen = config.servers[0]
    if server_name:
        for s in config.servers:
            if s.name == server_name:
                chosen = s
                break

    backend = [chosen.command, *chosen.args]

    server = GuardHTTPServer((host, port), proxy, backend, chosen.env)

    print(
        f"mcp-guard v0.1.2 HTTP gateway on {host}:{port}\n"
        f"  auth:      {config.auth.mode}\n"
        f"  backend:   {chosen.name} ({chosen.command})\n"
        f"  endpoints: POST /rpc, GET /health, GET /metrics\n"
        f"  audit:     {config.policies.audit_log or 'disabled'}\n",
        file=sys.stderr,
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nmcp-guard: shutting down", file=sys.stderr)
        server.shutdown()
        return 0

    return 0