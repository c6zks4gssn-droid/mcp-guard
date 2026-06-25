"""
MCPRouter — multi-server routing for mcp-guard.

Routes JSON-RPC requests to the right backend MCP server based on tool name,
method prefix, or explicit config. One mcp-guard gateway can now sit in front
of many MCP servers — clients see a single endpoint, the router fans out to
backends.

Three routing strategies (configured per request, in priority order):
  1. Explicit override:    method `_meta.target_server` → exact match
  2. Tool name match:      "tools/call" with params.name in routing map
  3. Method prefix match:  "notifications/" → first server that has it
  4. Default:              the first server in config.servers

Usage:
    config = GuardConfig.from_yaml("mcp-guard.yaml")
    router = MCPRouter(config.servers)
    chosen = router.route(raw_msg)
    if chosen is None:
        return error_response("no route")
    backend = [chosen.command, *chosen.args]
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .config import ServerConfig


@dataclass
class RouteRule:
    """A single routing rule.

    mode:
      "tool"     — match if tools/call.params.name == tool_name
      "method"   — match if JSON-RPC method starts with method_prefix
      "default"  — catch-all (lowest priority)

    target: name of the server in GuardConfig.servers
    """
    mode: str
    target: str
    tool_name: str = ""
    method_prefix: str = ""


@dataclass
class RouteConfig:
    """Routing rules applied in order. First match wins.

    Example:
        routes:
          - mode: tool
            tool_name: wallet_pay
            target: bonanza
          - mode: tool
            tool_name: search_docs
            target: filesystem
          - mode: method
            method_prefix: notifications/
            target: filesystem
          - mode: default
            target: bonanza
    """
    rules: list[RouteRule] = field(default_factory=list)


@dataclass
class MCPMessage:
    """Minimal mirror of proxy.MCPMessage for routing only."""
    id: Any = None
    method: str = ""
    params: dict = field(default_factory=dict)


class MCPRouter:
    """Selects the backend ServerConfig for a JSON-RPC message."""

    def __init__(
        self,
        servers: list[ServerConfig],
        routes: RouteConfig | None = None,
    ) -> None:
        if not servers:
            raise ValueError("MCPRouter requires at least one server")
        self.servers = servers
        self._by_name: dict[str, ServerConfig] = {s.name: s for s in servers}
        self.routes = routes or RouteConfig(rules=[
            RouteRule(mode="default", target=servers[0].name),
        ])

    def route(self, raw: dict) -> ServerConfig | None:
        """Return the ServerConfig for this message, or None if no rule matches."""
        msg = MCPMessage(
            id=raw.get("id"),
            method=raw.get("method", ""),
            params=raw.get("params") or {},
        )

        # 1. Explicit override via _meta.target_server
        meta = msg.params.get("_meta", {}) or {}
        if "target_server" in meta:
            target = meta["target_server"]
            if target in self._by_name:
                return self._by_name[target]
            return None  # explicit but unknown → fail loud

        # 2/3. Apply routing rules in order
        for rule in self.routes.rules:
            if rule.mode == "tool" and msg.method == "tools/call":
                tool_name = msg.params.get("name", "")
                if tool_name == rule.tool_name:
                    return self._by_name.get(rule.target)
            elif rule.mode == "method":
                if msg.method.startswith(rule.method_prefix):
                    return self._by_name.get(rule.target)
            elif rule.mode == "default":
                return self._by_name.get(rule.target)

        # Nothing matched → first server as last resort
        return self.servers[0]

    def list_routes(self) -> list[str]:
        """Human-readable summary of routes for logs/diagnostics."""
        lines = []
        for i, rule in enumerate(self.routes.rules, 1):
            if rule.mode == "tool":
                lines.append(f"  {i}. tool '{rule.tool_name}' → {rule.target}")
            elif rule.mode == "method":
                lines.append(f"  {i}. method prefix '{rule.method_prefix}' → {rule.target}")
            elif rule.mode == "default":
                lines.append(f"  {i}. default → {rule.target}")
        return lines
