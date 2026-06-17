"""Tests for mcp-guard — PYTHONPATH=. python3 tests/test_mcp_guard.py"""
import sys, time
sys.path.insert(0, ".")

from mcp_guard.config import GuardConfig, AuthConfig, PolicyConfig, RateLimitConfig, _expand
from mcp_guard.auth import ApiKeyAuth, JWTAuth, NoAuth, create_jwt
from mcp_guard.ratelimit import RateLimiter
from mcp_guard.audit import GuardAuditLog, GuardAuditEntry
from mcp_guard.proxy import MCPProxy, MCPMessage, _rpc_error

passed = failed = 0

def run(name, fn):
    global passed, failed
    try:
        fn()
        print(f"  ✓ {name}"); passed += 1
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"  ✗ {name}: {e}"); failed += 1

# ── Config ─────────────────────────────────────────
print("── Config ───────────────────────────────")

def test_from_dict_minimal():
    cfg = GuardConfig.from_dict({})
    assert cfg.auth.mode == "none"
    assert cfg.policies.max_spend_per_session == float("inf")
run("minimal config", test_from_dict_minimal)

def test_from_dict_full():
    cfg = GuardConfig.from_dict({
        "auth": {"mode": "api_key", "keys": ["sk-abc", "sk-def"]},
        "servers": {
            "bonanza": {"command": "bonanza-mcp serve"},
        },
        "policies": {
            "max_spend_per_session": 25.0,
            "require_approval_above": 5.0,
            "block_vendors": ["spam.com"],
            "rate_limit": {"requests_per_minute": 60},
        },
    })
    assert cfg.auth.mode == "api_key"
    assert "sk-abc" in cfg.auth.keys
    assert len(cfg.servers) == 1
    assert cfg.servers[0].name == "bonanza"
    assert cfg.policies.max_spend_per_session == 25.0
    assert cfg.policies.rate_limit.requests_per_minute == 60
run("full config from dict", test_from_dict_full)

def test_env_expand(monkeypatch=None):
    import os
    os.environ["TEST_SECRET"] = "my-secret-value"
    cfg = GuardConfig.from_dict({
        "auth": {"mode": "jwt", "jwt_secret": "${TEST_SECRET}"}
    })
    assert cfg.auth.jwt_secret == "my-secret-value"
run("env var expansion", test_env_expand)

def test_server_command_split():
    cfg = GuardConfig.from_dict({
        "servers": {"fs": {"command": "npx @mcp/server-filesystem /data"}}
    })
    srv = cfg.servers[0]
    assert srv.command == "npx"
    assert "@mcp/server-filesystem" in srv.args
run("command string split", test_server_command_split)


# ── Auth ───────────────────────────────────────────
print("── Auth ─────────────────────────────────")

def test_no_auth():
    a = NoAuth()
    r = a.verify({})
    assert r.success
    assert r.agent_id == "anonymous"
run("NoAuth allows all", test_no_auth)

def test_api_key_valid():
    a = ApiKeyAuth(["sk-agent-abc"])
    r = a.verify({"api_key": "sk-agent-abc"})
    assert r.success
    assert r.agent_id == "agent-1"
run("ApiKeyAuth valid key", test_api_key_valid)

def test_api_key_invalid():
    a = ApiKeyAuth(["sk-agent-abc"])
    r = a.verify({"api_key": "wrong-key"})
    assert not r.success
    assert "invalid" in r.error
run("ApiKeyAuth invalid key", test_api_key_invalid)

def test_api_key_missing():
    a = ApiKeyAuth(["sk-agent-abc"])
    r = a.verify({})
    assert not r.success
    assert "missing" in r.error
run("ApiKeyAuth missing key", test_api_key_missing)

def test_api_key_bearer():
    a = ApiKeyAuth(["sk-agent-abc"])
    r = a.verify({"authorization": "Bearer sk-agent-abc"})
    assert r.success
run("ApiKeyAuth bearer token", test_api_key_bearer)

def test_jwt_valid():
    secret = "test-secret-xyz"
    token = create_jwt(secret, "agent-007", ttl_seconds=3600)
    a = JWTAuth(secret)
    r = a.verify({"token": token})
    assert r.success
    assert r.agent_id == "agent-007"
run("JWTAuth valid token", test_jwt_valid)

def test_jwt_wrong_secret():
    token = create_jwt("correct-secret", "agent-007")
    a = JWTAuth("wrong-secret")
    r = a.verify({"token": token})
    assert not r.success
    assert "signature" in r.error
run("JWTAuth wrong secret rejected", test_jwt_wrong_secret)

def test_jwt_expired():
    import time as _time
    secret = "test-secret"
    token = create_jwt(secret, "agent", ttl_seconds=-1)  # already expired
    a = JWTAuth(secret)
    r = a.verify({"token": token})
    assert not r.success
    assert "expired" in r.error
run("JWTAuth expired token rejected", test_jwt_expired)

def test_jwt_malformed():
    a = JWTAuth("secret")
    r = a.verify({"token": "not.a.jwt"})
    # malformed payload — signature check fails first
    assert not r.success
run("JWTAuth malformed token", test_jwt_malformed)


# ── RateLimiter ────────────────────────────────────
print("── RateLimiter ──────────────────────────")

def test_unlimited():
    rl = RateLimiter()
    for _ in range(1000):
        r = rl.check_request("agent-1")
        assert r.allowed
run("unlimited rate limiter allows all", test_unlimited)

def test_rpm_allows_under_limit():
    rl = RateLimiter(requests_per_minute=5)
    for _ in range(5):
        r = rl.check_request("agent-1")
        assert r.allowed
run("rpm allows up to limit", test_rpm_allows_under_limit)

def test_rpm_blocks_over_limit():
    rl = RateLimiter(requests_per_minute=3)
    for _ in range(3):
        rl.check_request("agent-1")
    r = rl.check_request("agent-1")
    assert not r.allowed
    assert r.retry_after_seconds > 0
run("rpm blocks over limit", test_rpm_blocks_over_limit)

def test_rpm_isolated_per_agent():
    rl = RateLimiter(requests_per_minute=2)
    rl.check_request("agent-1")
    rl.check_request("agent-1")
    # agent-1 is at limit, agent-2 should still be allowed
    r = rl.check_request("agent-2")
    assert r.allowed
run("rpm isolated per agent", test_rpm_isolated_per_agent)

def test_spend_limit():
    rl = RateLimiter(spend_per_hour_usd=5.00)
    r1 = rl.check_spend("agent-1", 3.00)
    assert r1.allowed
    r2 = rl.check_spend("agent-1", 3.00)  # would exceed 5.00
    assert not r2.allowed
run("spend per hour limit", test_spend_limit)

def test_reset():
    rl = RateLimiter(requests_per_minute=2)
    rl.check_request("agent-1")
    rl.check_request("agent-1")
    rl.reset("agent-1")
    r = rl.check_request("agent-1")
    assert r.allowed
run("reset clears agent state", test_reset)


# ── GuardAuditLog ──────────────────────────────────
print("── GuardAuditLog ────────────────────────")

def test_audit_record():
    log = GuardAuditLog()
    log.record(GuardAuditEntry("allowed", "agent-1", "tools/call", "wallet_request", "sess-1"))
    assert len(log.entries_for_agent("agent-1")) == 1
run("audit record and retrieve", test_audit_record)

def test_audit_stats():
    log = GuardAuditLog()
    log.record(GuardAuditEntry("allowed",      "a", "tools/call", "search", "s1"))
    log.record(GuardAuditEntry("blocked",      "a", "tools/call", "wallet_request", "s1"))
    log.record(GuardAuditEntry("rate_limited", "a", "tools/call", "search", "s2"))
    stats = log.stats()
    assert stats["total"] == 3
    assert stats["by_decision"]["allowed"] == 1
    assert stats["by_decision"]["blocked"] == 1
run("audit stats", test_audit_stats)


# ── MCPProxy ───────────────────────────────────────
print("── MCPProxy ─────────────────────────────")

def _msg(method, tool=None, amount=None, api_key=None):
    params = {}
    if tool:
        params["name"] = tool
    if amount is not None:
        params["arguments"] = {"amount": amount}
    if api_key:
        params["_meta"] = {"api_key": api_key}
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}

def test_proxy_no_auth_allows():
    proxy = MCPProxy()
    result = proxy.intercept(_msg("tools/list"), session_id="sess-1")
    assert result.allowed
    assert result.agent_id == "anonymous"
run("no-auth proxy allows all", test_proxy_no_auth_allows)

def test_proxy_api_key_valid():
    from mcp_guard.auth import ApiKeyAuth
    proxy = MCPProxy(auth=ApiKeyAuth(["sk-abc"]))
    result = proxy.intercept(_msg("tools/list", api_key="sk-abc"), session_id="s1")
    assert result.allowed
    assert result.agent_id == "agent-1"
run("proxy with valid api_key", test_proxy_api_key_valid)

def test_proxy_api_key_invalid():
    from mcp_guard.auth import ApiKeyAuth
    proxy = MCPProxy(auth=ApiKeyAuth(["sk-abc"]))
    result = proxy.intercept(_msg("tools/list", api_key="wrong"), session_id="s1")
    assert not result.allowed
    assert result.error_response is not None
    assert result.error_response["error"]["code"] == -32001
run("proxy rejects invalid api_key", test_proxy_api_key_invalid)

def test_proxy_rate_limited():
    rl = RateLimiter(requests_per_minute=2)
    proxy = MCPProxy(rate_limiter=rl)
    proxy.intercept(_msg("tools/list"), "s1")
    proxy.intercept(_msg("tools/list"), "s1")
    result = proxy.intercept(_msg("tools/list"), "s1")
    assert not result.allowed
    assert result.error_response["error"]["code"] == -32029
run("proxy rate limits", test_proxy_rate_limited)

def test_proxy_spend_blocked():
    policy = PolicyConfig(max_spend_per_session=5.00)
    proxy = MCPProxy(policy=policy)
    # First payment: $3 — OK
    r1 = proxy.intercept(_msg("tools/call", "wallet_request", 3.00), "s1")
    assert r1.allowed
    # Second payment: $3 — would exceed $5 total
    r2 = proxy.intercept(_msg("tools/call", "wallet_request", 3.00), "s1")
    assert not r2.allowed
    assert r2.error_response["error"]["code"] == -32002
run("proxy blocks spend over session budget", test_proxy_spend_blocked)

def test_proxy_non_spend_tool_ignores_budget():
    policy = PolicyConfig(max_spend_per_session=0.01)
    proxy = MCPProxy(policy=policy)
    # search_web is not a spending tool — budget doesn't apply
    result = proxy.intercept(_msg("tools/call", "search_web"), "s1")
    assert result.allowed
run("non-spending tools bypass spend check", test_proxy_non_spend_tool_ignores_budget)

def test_proxy_audit_records():
    proxy = MCPProxy()
    proxy.intercept(_msg("tools/list"), "s1")
    proxy.intercept(_msg("tools/call", "search_web"), "s1")
    entries = proxy.audit_log.all_entries()
    assert len(entries) == 2
    assert all(e.decision == "allowed" for e in entries)
run("proxy records audit entries", test_proxy_audit_records)

def test_proxy_sessions_isolated():
    policy = PolicyConfig(max_spend_per_session=5.00)
    proxy = MCPProxy(policy=policy)
    # Two different sessions — each has its own budget
    r1 = proxy.intercept(_msg("tools/call", "wallet_request", 4.00), "sess-A")
    r2 = proxy.intercept(_msg("tools/call", "wallet_request", 4.00), "sess-B")
    assert r1.allowed and r2.allowed
run("session budgets are isolated", test_proxy_sessions_isolated)

def test_rpc_error_format():
    err = _rpc_error(42, -32001, "Unauthorized")
    assert err["id"] == 42
    assert err["error"]["code"] == -32001
    assert "Unauthorized" in err["error"]["message"]
run("JSON-RPC error format", test_rpc_error_format)

print(f"\n── Results ─────────────────────────────")
print(f"  {passed} passed  {failed} failed")
