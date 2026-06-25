"""Tests for v0.1.4: multi-server routing + OAuth2 provider."""

import time
import pytest

from mcp_guard.config import ServerConfig
from mcp_guard.router import MCPRouter, RouteConfig, RouteRule
from mcp_guard.oauth import (
    OAuth2Provider,
    OAuth2Auth,
    generate_pkce_pair,
    generate_state,
)


@pytest.fixture
def two_servers() -> list[ServerConfig]:
    return [
        ServerConfig.from_dict("bonanza", {"command": "bonanza-mcp serve"}),
        ServerConfig.from_dict("filesystem", {"command": "npx server-filesystem /data"}),
        ServerConfig.from_dict("search", {"command": "python -m search_server"}),
    ]


# ── Multi-server routing ──────────────────────────────────────

class TestMCPRouter:
    def test_default_to_first_server(self, two_servers):
        router = MCPRouter(two_servers)
        msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        chosen = router.route(msg)
        assert chosen is not None
        assert chosen.name == "bonanza"

    def test_tool_name_routing(self, two_servers):
        router = MCPRouter(two_servers, RouteConfig(rules=[
            RouteRule(mode="tool", target="filesystem", tool_name="read_file"),
            RouteRule(mode="tool", target="search", tool_name="search_docs"),
            RouteRule(mode="default", target="bonanza"),
        ]))
        chosen = router.route({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "read_file"},
        })
        assert chosen.name == "filesystem"

        chosen = router.route({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "search_docs"},
        })
        assert chosen.name == "search"

        # Unknown tool falls through to default
        chosen = router.route({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "wallet_pay"},
        })
        assert chosen.name == "bonanza"

    def test_method_prefix_routing(self, two_servers):
        router = MCPRouter(two_servers, RouteConfig(rules=[
            RouteRule(mode="method", target="filesystem", method_prefix="notifications/"),
            RouteRule(mode="default", target="bonanza"),
        ]))
        chosen = router.route({
            "jsonrpc": "2.0", "id": 1, "method": "notifications/message",
        })
        assert chosen.name == "filesystem"

    def test_explicit_meta_override(self, two_servers):
        router = MCPRouter(two_servers)
        chosen = router.route({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "anything", "_meta": {"target_server": "search"}},
        })
        assert chosen.name == "search"

    def test_unknown_explicit_target_returns_none(self, two_servers):
        router = MCPRouter(two_servers)
        chosen = router.route({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"_meta": {"target_server": "nonexistent"}},
        })
        assert chosen is None

    def test_needs_at_least_one_server(self):
        with pytest.raises(ValueError):
            MCPRouter([])

    def test_list_routes(self, two_servers):
        router = MCPRouter(two_servers, RouteConfig(rules=[
            RouteRule(mode="tool", target="filesystem", tool_name="read_file"),
            RouteRule(mode="default", target="bonanza"),
        ]))
        routes = router.list_routes()
        assert any("tool 'read_file'" in r for r in routes)
        assert any("default" in r for r in routes)


# ── OAuth2 provider ───────────────────────────────────────────

class TestOAuth2AuthCodeFlow:
    def test_pkce_s256_round_trip(self):
        oauth = OAuth2Provider()
        verifier, challenge = generate_pkce_pair()
        assert len(verifier) > 40
        assert len(challenge) > 40

        ac = oauth.authorize(
            client_id="mcp-agent",
            agent_id="agent-1",
            code_challenge=challenge,
            code_challenge_method="S256",
        )
        assert ac is not None

        # Token exchange with correct verifier
        tr = oauth.token_exchange(
            grant_type="authorization_code",
            code=ac.code,
            code_verifier=verifier,
            client_id="mcp-agent",
        )
        assert tr is not None
        assert tr.access_token
        assert tr.refresh_token

    def test_pkce_wrong_verifier_rejected(self):
        oauth = OAuth2Provider()
        _, challenge = generate_pkce_pair()
        ac = oauth.authorize("mcp-agent", "agent-1", challenge, "S256")

        tr = oauth.token_exchange(
            "authorization_code", ac.code, "wrong-verifier", "mcp-agent"
        )
        assert tr is None

    def test_code_can_only_be_used_once(self):
        oauth = OAuth2Provider()
        verifier, challenge = generate_pkce_pair()
        ac = oauth.authorize("mcp-agent", "agent-1", challenge, "S256")

        oauth.token_exchange("authorization_code", ac.code, verifier, "mcp-agent")
        # Second use fails
        again = oauth.token_exchange("authorization_code", ac.code, verifier, "mcp-agent")
        assert again is None

    def test_code_expires(self):
        oauth = OAuth2Provider(code_ttl=1)
        verifier, challenge = generate_pkce_pair()
        ac = oauth.authorize("mcp-agent", "agent-1", challenge, "S256")
        time.sleep(1.1)
        tr = oauth.token_exchange("authorization_code", ac.code, verifier, "mcp-agent")
        assert tr is None

    def test_wrong_client_id_rejected(self):
        oauth = OAuth2Provider()
        verifier, challenge = generate_pkce_pair()
        ac = oauth.authorize("mcp-agent", "agent-1", challenge, "S256")
        # Mismatched client_id in token request is rejected
        tr = oauth.token_exchange(
            grant_type="authorization_code",
            code=ac.code,
            code_verifier=verifier,
            client_id="wrong-client",
        )
        assert tr is None

    def test_refresh_token_works_once(self):
        oauth = OAuth2Provider()
        verifier, challenge = generate_pkce_pair()
        ac = oauth.authorize("mcp-agent", "agent-1", challenge, "S256")
        tr = oauth.token_exchange("authorization_code", ac.code, verifier, "mcp-agent")
        assert tr is not None

        # Refresh
        refreshed = oauth.token_exchange(
            "refresh_token", refresh_token=tr.refresh_token, client_id="mcp-agent"
        )
        assert refreshed is not None
        assert refreshed.access_token != tr.access_token

        # Old refresh token no longer valid
        again = oauth.token_exchange(
            "refresh_token", refresh_token=tr.refresh_token, client_id="mcp-agent"
        )
        assert again is None

    def test_introspect_and_revoke(self):
        oauth = OAuth2Provider()
        verifier, challenge = generate_pkce_pair()
        ac = oauth.authorize("mcp-agent", "agent-1", challenge, "S256")
        tr = oauth.token_exchange("authorization_code", ac.code, verifier, "mcp-agent")

        info = oauth.introspect(tr.access_token)
        assert info is not None
        assert info["active"] is True
        assert info["sub"] == "agent-1"

        assert oauth.revoke(tr.access_token) is True
        assert oauth.introspect(tr.access_token) is None


class TestOAuth2DeviceFlow:
    def test_full_device_flow(self):
        oauth = OAuth2Provider()
        device = oauth.device_authorize("mcp-agent")
        assert device is not None
        assert "-" in device.user_code

        # Poll before approval → pending
        result = oauth.device_poll(device.device_code, "mcp-agent")
        assert isinstance(result, dict)
        assert result["error"] == "authorization_pending"

        # Approve
        assert oauth.device_approve(device.user_code, "agent-1") is True

        # Poll after approval → token
        result = oauth.device_poll(device.device_code, "mcp-agent")
        assert hasattr(result, "access_token")
        assert result.access_token


class TestOAuth2AuthProvider:
    def test_verify_bearer_token(self):
        oauth = OAuth2Provider()
        verifier, challenge = generate_pkce_pair()
        ac = oauth.authorize("mcp-agent", "agent-1", challenge, "S256")
        tr = oauth.token_exchange("authorization_code", ac.code, verifier, "mcp-agent")

        auth = OAuth2Auth(oauth)
        result = auth.verify({"authorization": f"Bearer {tr.access_token}"})
        assert result.success is True
        assert result.agent_id == "agent-1"

    def test_rejects_expired_token(self):
        oauth = OAuth2Provider(access_token_ttl=1)
        verifier, challenge = generate_pkce_pair()
        ac = oauth.authorize("mcp-agent", "agent-1", challenge, "S256")
        tr = oauth.token_exchange("authorization_code", ac.code, verifier, "mcp-agent")
        time.sleep(1.1)

        auth = OAuth2Auth(oauth)
        result = auth.verify({"authorization": f"Bearer {tr.access_token}"})
        assert result.success is False

    def test_rejects_missing_bearer(self):
        oauth = OAuth2Provider()
        auth = OAuth2Auth(oauth)
        result = auth.verify({"authorization": "Bearer"})
        assert result.success is False

    def test_state_helper_uniqueness(self):
        a = generate_state()
        b = generate_state()
        assert a != b
        assert len(a) >= 20
