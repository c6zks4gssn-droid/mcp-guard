"""
OAuth2 provider for mcp-guard v0.1.4.

Implements RFC 6749 (Authorization Code Grant) + RFC 7636 (PKCE) so
agents can authenticate via OAuth2 instead of static API keys.

Flow:
    1. Agent generates code_verifier + code_challenge (PKCE).
    2. Agent visits /oauth/authorize?response_type=code&client_id=...&...
       (in a real flow this is interactive — for MCP agents we use the
       /oauth/device flow or pre-issued codes)
    3. mcp-guard returns an authorization code.
    4. Agent POSTs to /oauth/token with code + code_verifier.
    5. mcp-guard returns {access_token, refresh_token, expires_in}.
    6. Agent sends Authorization: Bearer <access_token> on each MCP call.

For agentic (non-interactive) flows we also implement RFC 8628
Device Authorization Grant — see `DeviceAuthRequest`.

Storage: in-memory dict by default. For multi-replica production,
swap the `_codes` and `_tokens` dicts for a database.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

from .auth import AuthProvider, AuthResult


@dataclass
class AuthorizationCode:
    code: str
    client_id: str
    agent_id: str
    code_challenge: str
    code_challenge_method: str  # "S256" | "plain"
    redirect_uri: str
    scope: str
    expires_at: float
    used: bool = False


@dataclass
class AccessToken:
    access_token: str
    refresh_token: str
    client_id: str
    agent_id: str
    scope: str
    expires_at: float


@dataclass
class TokenResponse:
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600
    refresh_token: str = ""
    scope: str = ""


@dataclass
class DeviceAuthRequest:
    """RFC 8628 device flow — for headless agents."""
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_at: float
    interval: int = 5
    approved: bool = False
    approved_agent_id: str = ""


class OAuth2Provider:
    """
    In-memory OAuth2 server. Handles auth code + PKCE, token exchange,
    refresh, introspection. Plug a custom backend for persistence.
    """

    def __init__(
        self,
        client_id: str = "mcp-agent",
        client_secret: str = "",
        issuer: str = "mcp-guard",
        access_token_ttl: int = 3600,
        refresh_token_ttl: int = 86400 * 30,
        code_ttl: int = 600,
        device_code_ttl: int = 600,
        device_poll_interval: int = 5,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.issuer = issuer
        self.access_token_ttl = access_token_ttl
        self.refresh_token_ttl = refresh_token_ttl
        self.code_ttl = code_ttl
        self.device_code_ttl = device_code_ttl
        self.device_poll_interval = device_poll_interval

        self._codes: dict[str, AuthorizationCode] = {}
        self._tokens: dict[str, AccessToken] = {}  # by access_token
        self._by_refresh: dict[str, AccessToken] = {}  # by refresh_token
        self._devices: dict[str, DeviceAuthRequest] = {}

    # ── Authorization Code + PKCE ─────────────────────────────

    def authorize(
        self,
        client_id: str,
        agent_id: str,
        code_challenge: str,
        code_challenge_method: str = "S256",
        redirect_uri: str = "",
        scope: str = "mcp",
    ) -> AuthorizationCode | None:
        """Issue an authorization code. Agent must then exchange it for a token."""
        if client_id != self.client_id:
            return None
        if code_challenge_method not in ("S256", "plain"):
            return None

        code = AuthorizationCode(
            code=secrets.token_urlsafe(32),
            client_id=client_id,
            agent_id=agent_id,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            redirect_uri=redirect_uri,
            scope=scope,
            expires_at=time.time() + self.code_ttl,
        )
        self._codes[code.code] = code
        return code

    def token_exchange(
        self,
        grant_type: str,
        code: str = "",
        code_verifier: str = "",
        refresh_token: str = "",
        client_id: str = "",
    ) -> TokenResponse | None:
        if grant_type == "authorization_code":
            return self._exchange_code(code, code_verifier, client_id)
        if grant_type == "refresh_token":
            return self._exchange_refresh(refresh_token, client_id)
        return None

    def _exchange_code(
        self, code: str, code_verifier: str, client_id: str
    ) -> TokenResponse | None:
        ac = self._codes.get(code)
        if not ac or ac.used or ac.expires_at < time.time():
            return None
        # If a client_id was provided, it must match the one bound to the code
        if client_id and client_id != ac.client_id:
            return None
        # Verify PKCE
        if ac.code_challenge_method == "S256":
            expected = _b64url_no_pad(
                hashlib.sha256(code_verifier.encode()).digest()
            )
            if not hmac.compare_digest(expected, ac.code_challenge):
                return None
        else:  # plain
            if code_verifier != ac.code_challenge:
                return None
        ac.used = True
        return self._issue_token(ac.client_id, ac.agent_id, ac.scope)

    def _exchange_refresh(
        self, refresh_token: str, client_id: str
    ) -> TokenResponse | None:
        existing = self._by_refresh.get(refresh_token)
        if not existing or existing.expires_at < time.time():
            return None
        if client_id and client_id != existing.client_id:
            return None
        # Revoke old tokens, issue fresh pair
        self._tokens.pop(existing.access_token, None)
        self._by_refresh.pop(refresh_token, None)
        return self._issue_token(existing.client_id, existing.agent_id, existing.scope)

    def _issue_token(self, client_id: str, agent_id: str, scope: str) -> TokenResponse:
        access = secrets.token_urlsafe(48)
        refresh = secrets.token_urlsafe(48)
        token = AccessToken(
            access_token=access,
            refresh_token=refresh,
            client_id=client_id,
            agent_id=agent_id,
            scope=scope,
            expires_at=time.time() + self.access_token_ttl,
        )
        self._tokens[access] = token
        self._by_refresh[refresh] = token
        return TokenResponse(
            access_token=access,
            expires_in=self.access_token_ttl,
            refresh_token=refresh,
            scope=scope,
        )

    # ── Device Authorization Grant (RFC 8628) ────────────────

    def device_authorize(self, client_id: str, scope: str = "mcp") -> DeviceAuthRequest | None:
        if client_id != self.client_id:
            return None
        user_code = "-".join([
            secrets.token_hex(2).upper(),
            secrets.token_hex(2).upper(),
        ])
        device = DeviceAuthRequest(
            device_code=secrets.token_urlsafe(32),
            user_code=user_code,
            verification_uri=f"https://{self.issuer}/oauth/device",
            verification_uri_complete=f"https://{self.issuer}/oauth/device?code={user_code}",
            expires_at=time.time() + self.device_code_ttl,
            interval=self.device_poll_interval,
        )
        self._devices[device.device_code] = device
        return device

    def device_approve(self, user_code: str, agent_id: str) -> bool:
        for device in self._devices.values():
            if device.user_code == user_code and not device.approved:
                device.approved = True
                device.approved_agent_id = agent_id
                return True
        return False

    def device_poll(
        self, device_code: str, client_id: str
    ) -> TokenResponse | dict | None:
        """Return a TokenResponse, or {"error": "authorization_pending"}."""
        device = self._devices.get(device_code)
        if not device or device.expires_at < time.time():
            return {"error": "expired_token"}
        if client_id != self.client_id:
            return {"error": "invalid_client"}
        if not device.approved:
            return {"error": "authorization_pending"}
        return self._issue_token(self.client_id, device.approved_agent_id, "mcp")

    # ── Token introspection (RFC 7662 lite) ──────────────────

    def introspect(self, access_token: str) -> dict | None:
        token = self._tokens.get(access_token)
        if not token or token.expires_at < time.time():
            return None
        return {
            "active": True,
            "client_id": token.client_id,
            "sub": token.agent_id,
            "scope": token.scope,
            "exp": int(token.expires_at),
        }

    # ── Revocation (RFC 7009 lite) ───────────────────────────

    def revoke(self, access_token: str) -> bool:
        token = self._tokens.pop(access_token, None)
        if not token:
            return False
        self._by_refresh.pop(token.refresh_token, None)
        return True


class OAuth2Auth(AuthProvider):
    """
    AuthProvider backed by an OAuth2Provider. Tokens come in via:
      credentials = {"authorization": "Bearer <access_token>"}
    or:
      credentials = {"token": "<access_token>"}
    """

    def __init__(self, oauth: OAuth2Provider) -> None:
        self._oauth = oauth

    def verify(self, credentials: dict) -> AuthResult:
        token = (
            credentials.get("token")
            or _bearer(credentials.get("authorization", ""))
        )
        if not token:
            return AuthResult(success=False, error="missing bearer token")

        info = self._oauth.introspect(token)
        if not info or not info.get("active"):
            return AuthResult(success=False, error="invalid or expired token")

        return AuthResult(success=True, agent_id=info.get("sub", "unknown"))


# ── PKCE helpers ──────────────────────────────────────────────

def generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) using S256."""
    verifier = _b64url_no_pad(secrets.token_bytes(32))
    challenge = _b64url_no_pad(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


def generate_state() -> str:
    """Return a random state parameter for CSRF protection."""
    return secrets.token_urlsafe(24)


# ── helpers ───────────────────────────────────────────────────

def _bearer(header: str) -> str:
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""


def _b64url_no_pad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
