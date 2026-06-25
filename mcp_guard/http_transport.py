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
from .router import MCPRouter, RouteConfig, RouteRule


class GuardHTTPHandler(BaseHTTPRequestHandler):
    """HTTP handler for mcp-guard."""

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(200, {"status": "ok", "version": "0.1.4"})
        elif self.path == "/metrics":
            self._prometheus()
        elif self.path.startswith("/oauth/authorize"):
            self._oauth_authorize()
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path == "/rpc":
            self._handle_rpc()
        elif self.path == "/oauth/token":
            self._oauth_token()
        elif self.path.startswith("/oauth/device/approve"):
            self._oauth_device_approve()
        elif self.path == "/oauth/introspect":
            self._oauth_introspect()
        elif self.path == "/oauth/revoke":
            self._oauth_revoke()
        else:
            self._json(404, {"error": "not found"})

    def _handle_rpc(self) -> None:
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

    def _oauth_authorize(self) -> None:
        """GET /oauth/authorize?response_type=code&client_id=...&...&code_challenge=..."""
        oauth = getattr(self.server, "oauth", None)
        if oauth is None:
            self._json(503, {"error": "oauth_not_enabled"})
            return
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(self.path).query)
        client_id = q.get("client_id", [""])[0]
        agent_id = q.get("agent_id", ["anonymous"])[0]
        challenge = q.get("code_challenge", [""])[0]
        method = q.get("code_challenge_method", ["S256"])[0]
        scope = q.get("scope", ["mcp"])[0]
        ac = oauth.authorize(client_id, agent_id, challenge, method, scope=scope)
        if ac is None:
            self._json(400, {"error": "invalid_request"})
            return
        self._json(200, {"code": ac.code, "expires_in": oauth.code_ttl})

    def _oauth_token(self) -> None:
        """POST /oauth/token — grant_type=authorization_code | refresh_token."""
        oauth = getattr(self.server, "oauth", None)
        if oauth is None:
            self._json(503, {"error": "oauth_not_enabled"})
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            data = {}
        # Allow form-encoded too
        if not data:
            from urllib.parse import parse_qs
            data = {k: v[0] for k, v in parse_qs(body.decode()).items()}

        grant_type = data.get("grant_type", "")
        response = oauth.token_exchange(
            grant_type=grant_type,
            code=data.get("code", ""),
            code_verifier=data.get("code_verifier", ""),
            refresh_token=data.get("refresh_token", ""),
            client_id=data.get("client_id", ""),
        )
        if response is None:
            self._json(400, {"error": "invalid_grant"})
            return
        # Device flow errors come back as {"error": "..."}
        if isinstance(response, dict) and "error" in response:
            self._json(400, response)
            return
        self._json(200, {
            "access_token": response.access_token,
            "token_type": response.token_type,
            "expires_in": response.expires_in,
            "refresh_token": response.refresh_token,
            "scope": response.scope,
        })

    def _oauth_device_approve(self) -> None:
        """POST /oauth/device/approve  body={"user_code": "...", "agent_id": "..."}."""
        oauth = getattr(self.server, "oauth", None)
        if oauth is None:
            self._json(503, {"error": "oauth_not_enabled"})
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid_json"})
            return
        ok = oauth.device_approve(
            data.get("user_code", ""), data.get("agent_id", "")
        )
        self._json(200 if ok else 404, {"approved": ok})

    def _oauth_introspect(self) -> None:
        oauth = getattr(self.server, "oauth", None)
        if oauth is None:
            self._json(503, {"error": "oauth_not_enabled"})
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        from urllib.parse import parse_qs
        data = {k: v[0] for k, v in parse_qs(body.decode()).items()}
        info = oauth.introspect(data.get("token", ""))
        if info is None:
            self._json(200, {"active": False})
            return
        self._json(200, info)

    def _oauth_revoke(self) -> None:
        oauth = getattr(self.server, "oauth", None)
        if oauth is None:
            self._json(503, {"error": "oauth_not_enabled"})
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        from urllib.parse import parse_qs
        data = {k: v[0] for k, v in parse_qs(body.decode()).items()}
        ok = oauth.revoke(data.get("token", ""))
        self._json(200, {"revoked": ok})

    def do_POST(self) -> None:
        if self.path == "/rpc":
            self._handle_rpc()
        elif self.path == "/oauth/token":
            self._oauth_token()
        elif self.path.startswith("/oauth/device/approve"):
            self._oauth_device_approve()
        elif self.path == "/oauth/introspect":
            self._oauth_introspect()
        elif self.path == "/oauth/revoke":
            self._oauth_revoke()
        else:
            self._json(404, {"error": "not found"})

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
    """HTTP server with mcp-guard proxy + router attached."""

    proxy: MCPProxy
    router: MCPRouter | None  # v0.1.4 — None when only one server
    oauth: Any  # v0.1.4 — OAuth2Provider | None

    def __init__(
        self,
        addr: tuple[str, int],
        proxy: MCPProxy,
        router: MCPRouter | None = None,
        oauth: Any = None,
        # Backwards-compat shim: legacy callers pass (backend_command, backend_env)
        _legacy_backend: Any = None,
        _legacy_env: Any = None,
    ) -> None:
        super().__init__(addr, GuardHTTPHandler)
        self.proxy = proxy
        # If positional 3rd arg is a list/tuple, treat as legacy backend_command
        if isinstance(router, (list, tuple)) and not isinstance(router, MCPRouter):
            self._legacy_backend = list(router)
            self._legacy_env = _legacy_env if isinstance(_legacy_env, dict) else {}
            self.router = None
        else:
            self._legacy_backend = None
            self._legacy_env = {}
            self.router = router
        self.oauth = oauth

    def _forward_to_backend(self, raw: dict, server: "GuardHTTPServer") -> dict:
        """Forward a JSON-RPC message to the selected backend MCP server and return response."""
        import os
        import subprocess as sp

        # Pick backend — either via router or fall back to legacy single backend
        if server.router:
            chosen = server.router.route(raw)
            if chosen is None:
                return {
                    "jsonrpc": "2.0",
                    "id": raw.get("id"),
                    "error": {
                        "code": -32005,
                        "message": "No route matched for this request",
                    },
                }
            backend_cmd = [chosen.command, *chosen.args]
            backend_env = chosen.env
        elif getattr(server, "_legacy_backend", None):
            chosen = None
            backend_cmd = server._legacy_backend
            backend_env = server._legacy_env or {}
        else:
            chosen = None
            backend_cmd = []
            backend_env = {}

        if not backend_cmd:
            return {
                "jsonrpc": "2.0",
                "id": raw.get("id"),
                "error": {"code": -32603, "message": "No backend configured"},
            }

        try:
            proc = sp.Popen(
                backend_cmd,
                stdin=sp.PIPE,
                stdout=sp.PIPE,
                stderr=sp.PIPE,
                env={**os.environ, **backend_env},
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
    if not config.servers:
        print("mcp-guard: no servers configured", file=sys.stderr)
        return 1

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

    # Build router from config.routes (v0.1.4)
    if config.routes:
        rules = []
        for r in config.routes:
            rules.append(RouteRule(
                mode=r.get("mode", "default"),
                target=r.get("target", config.servers[0].name),
                tool_name=r.get("tool_name", ""),
                method_prefix=r.get("method_prefix", ""),
            ))
        if not any(rule.mode == "default" for rule in rules):
            rules.append(RouteRule(mode="default", target=config.servers[0].name))
        router = MCPRouter(config.servers, RouteConfig(rules=rules))
    elif len(config.servers) == 1:
        # Legacy: no router, single server
        router = None
    elif server_name:
        # Backwards-compat: --server flag
        chosen = next((s for s in config.servers if s.name == server_name), config.servers[0])
        router = MCPRouter(config.servers, RouteConfig(rules=[RouteRule(mode="default", target=chosen.name)]))
    else:
        # Multiple servers but no routes → default to first
        router = MCPRouter(config.servers)

    # Build OAuth2 provider if config requests it (v0.1.4)
    oauth = None
    if config.auth.mode == "oauth2":
        from .oauth import OAuth2Provider
        oauth = OAuth2Provider(
            client_id=getattr(config.auth, "client_id", "mcp-agent"),
            client_secret=getattr(config.auth, "client_secret", ""),
            issuer=getattr(config.auth, "issuer", "mcp-guard"),
        )

    server = GuardHTTPServer((host, port), proxy, router, oauth)

    print(
        f"mcp-guard v0.1.4 HTTP gateway on {host}:{port}\n"
        f"  auth:      {config.auth.mode}\n"
        f"  servers:   {', '.join(s.name for s in config.servers)}\n"
        f"  routes:    {len(config.routes) if config.routes else 'default-first'}\n"
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