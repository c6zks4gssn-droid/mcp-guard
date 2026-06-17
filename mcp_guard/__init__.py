"""
mcp-guard: Production-grade security gateway for MCP servers.

Sits in front of any MCP server and enforces:
- JWT / API-key authentication
- Per-agent rate limiting
- Spending caps (via x402-firewall policy engine)
- Full audit logging

Usage:
    pip install mcp-guard
    mcp-guard serve --config mcp-guard.yaml

Or in Claude Desktop config:
    {
      "mcpServers": {
        "guarded": {
          "command": "mcp-guard",
          "args": ["serve", "--config", "/path/to/mcp-guard.yaml"]
        }
      }
    }
"""

from .config import GuardConfig, ServerConfig, PolicyConfig, AuthConfig
from .auth import AuthProvider, JWTAuth, ApiKeyAuth, AuthResult
from .ratelimit import RateLimiter
from .proxy import MCPProxy
from .audit import GuardAuditLog, GuardAuditEntry

__version__ = "0.1.0"
__all__ = [
    "GuardConfig",
    "ServerConfig",
    "PolicyConfig",
    "AuthConfig",
    "AuthProvider",
    "JWTAuth",
    "ApiKeyAuth",
    "AuthResult",
    "RateLimiter",
    "MCPProxy",
    "GuardAuditLog",
    "GuardAuditEntry",
]
