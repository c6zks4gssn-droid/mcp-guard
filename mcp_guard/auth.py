"""
Authentication provider for mcp-guard.

Supports:
- "none"    → all requests pass (dev/local mode)
- "api_key" → Bearer token or X-API-Key header must match configured keys
- "jwt"     → signed JWT, verified with HMAC-SHA256 secret

The MCP protocol (JSON-RPC over STDIO) doesn't have HTTP headers, so
mcp-guard reads auth from the `_meta` field of each JSON-RPC request:

    {
      "jsonrpc": "2.0",
      "method": "tools/call",
      "params": {
        "_meta": { "api_key": "sk-agent-abc123" },
        "name": "wallet_request",
        "arguments": { ... }
      }
    }

For HTTP/SSE transport, the standard Authorization header is used.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Literal


@dataclass
class AuthResult:
    success: bool
    agent_id: str = "anonymous"
    error: str = ""


class AuthProvider:
    """Base class."""

    def verify(self, credentials: dict) -> AuthResult:
        raise NotImplementedError


class NoAuth(AuthProvider):
    """Accept all requests. Use in local/dev mode only."""

    def verify(self, credentials: dict) -> AuthResult:
        return AuthResult(success=True, agent_id="anonymous")


class ApiKeyAuth(AuthProvider):
    """
    Verify against a list of pre-configured API keys.

    Keys should be passed in:
        credentials = {"api_key": "sk-agent-abc123"}
    or
        credentials = {"authorization": "Bearer sk-agent-abc123"}
    """

    def __init__(self, valid_keys: list[str]) -> None:
        # Store as set of (key_hash) to avoid timing attacks
        self._hashes: set[bytes] = {
            hashlib.sha256(k.encode()).digest() for k in valid_keys
        }
        self._key_to_id: dict[str, str] = {
            k: f"agent-{i+1}" for i, k in enumerate(valid_keys)
        }
        self._valid_keys = valid_keys

    def verify(self, credentials: dict) -> AuthResult:
        key = (
            credentials.get("api_key")
            or _bearer(credentials.get("authorization", ""))
        )
        if not key:
            return AuthResult(success=False, error="missing api_key")

        key_hash = hashlib.sha256(key.encode()).digest()
        if key_hash not in self._hashes:
            return AuthResult(success=False, error="invalid api_key")

        agent_id = self._key_to_id.get(key, "unknown")
        return AuthResult(success=True, agent_id=agent_id)


class JWTAuth(AuthProvider):
    """
    Minimal HMAC-SHA256 JWT verification (no external dependencies).

    Token format: base64url(header).base64url(payload).base64url(signature)
    where signature = HMAC-SHA256(secret, header + "." + payload)

    The payload must include:
        { "sub": "agent-id", "exp": <unix timestamp> }

    Use mcp_guard.auth.create_jwt() to issue tokens.
    """

    def __init__(self, secret: str) -> None:
        self._secret = secret.encode()

    def verify(self, credentials: dict) -> AuthResult:
        token = (
            credentials.get("token")
            or _bearer(credentials.get("authorization", ""))
        )
        if not token:
            return AuthResult(success=False, error="missing token")

        parts = token.split(".")
        if len(parts) != 3:
            return AuthResult(success=False, error="malformed jwt")

        header_b64, payload_b64, sig_b64 = parts
        expected_sig = hmac.new(
            self._secret,
            f"{header_b64}.{payload_b64}".encode(),
            hashlib.sha256,
        ).digest()
        try:
            provided_sig = _b64decode(sig_b64)
        except Exception:
            return AuthResult(success=False, error="malformed signature")

        if not hmac.compare_digest(expected_sig, provided_sig):
            return AuthResult(success=False, error="invalid signature")

        try:
            payload = json.loads(_b64decode(payload_b64).decode())
        except Exception:
            return AuthResult(success=False, error="malformed payload")

        exp = payload.get("exp", 0)
        if exp and time.time() > exp:
            return AuthResult(success=False, error="token expired")

        agent_id = payload.get("sub", "unknown")
        return AuthResult(success=True, agent_id=agent_id)


def create_jwt(secret: str, agent_id: str, ttl_seconds: int = 3600) -> str:
    """Issue a signed JWT for an agent (no external dependencies)."""
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64encode(
        json.dumps({"sub": agent_id, "exp": int(time.time()) + ttl_seconds}).encode()
    )
    sig = hmac.new(
        secret.encode(),
        f"{header}.{payload}".encode(),
        hashlib.sha256,
    ).digest()
    return f"{header}.{payload}.{_b64encode(sig)}"


def build_auth_provider(config) -> AuthProvider:
    """Factory: build the right AuthProvider from a config object."""
    mode = getattr(config, "mode", "none")
    if mode == "api_key":
        return ApiKeyAuth(config.keys)
    elif mode == "jwt":
        return JWTAuth(config.jwt_secret)
    elif mode == "oauth2":
        from .oauth import OAuth2Auth
        # config may carry an OAuth2Provider instance, or we build a fresh one
        oauth = getattr(config, "_oauth_provider", None)
        if oauth is None:
            from .oauth import OAuth2Provider
            oauth = OAuth2Provider(
                client_id=getattr(config, "client_id", "mcp-agent"),
                client_secret=getattr(config, "client_secret", ""),
                issuer=getattr(config, "issuer", "mcp-guard"),
            )
        return OAuth2Auth(oauth)
    else:
        return NoAuth()


# ── helpers ────────────────────────────────────────────────────

def _bearer(header: str) -> str:
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)
