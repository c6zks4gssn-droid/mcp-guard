# mcp-guard

**Production-grade security gateway for MCP servers.**

```bash
pip install "mcp-guard[yaml]"
# or from source: pip install "git+https://github.com/c6zks4gssn-droid/mcp-guard.git#egg=mcp-guard[yaml]"
mcp-guard scan
mcp-guard serve --config mcp-guard.yaml
```

Sits in front of any MCP server and enforces authentication, rate limiting, spending controls, and full audit logging. Zero required dependencies.

---

## The problem

A security audit in June 2026 found **1,862 internet-exposed MCP servers** — 100% of manually verified servers had **no authentication**. Any MCP client can call any tool on any server with no identity verification and no audit trail.

`mcp-guard` fixes this without changing your MCP servers.

---

## Quickstart

**1. Install**
```bash
pip install "mcp-guard[yaml]"
```

**1b. Audit your machine (no server needed)**
```bash
mcp-guard scan
```

**2. Configure (`mcp-guard.yaml`)**
```yaml
auth:
  mode: api_key
  keys:
    - "sk-agent-abc123"
    - "sk-agent-def456"

servers:
  bonanza:
    command: bonanza-mcp serve
    env:
      BONANZA_API_KEY: "${BONANZA_API_KEY}"
  filesystem:
    command: npx @modelcontextprotocol/server-filesystem /data

policies:
  max_spend_per_session: 10.00
  require_approval_above: 2.00
  block_vendors:
    - "untrusted.com"
  audit_log: /var/log/mcp-guard.jsonl
  rate_limit:
    requests_per_minute: 100
    spend_per_hour_usd: 50.00
```

**3. Add to Claude Desktop**
```json
{
  "mcpServers": {
    "guarded": {
      "command": "mcp-guard",
      "args": ["serve", "--config", "/path/to/mcp-guard.yaml"]
    }
  }
}
```

**4. Agents must include auth in requests**
```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "_meta": { "api_key": "sk-agent-abc123" },
    "name": "wallet_request",
    "arguments": { "amount": 1.50 }
  }
}
```

---

## Authentication modes

### API Key (simplest)
```yaml
auth:
  mode: api_key
  keys:
    - "sk-agent-abc123"
    - "sk-prod-xyz789"
```

Keys can be in `_meta.api_key`, `_meta.token`, `Authorization: Bearer ...`, or `X-API-Key`.

### JWT (for multi-agent systems)
```yaml
auth:
  mode: jwt
  jwt_secret: "${JWT_SECRET}"
```

Issue tokens:
```python
from mcp_guard.auth import create_jwt
token = create_jwt(secret="my-secret", agent_id="agent-007", ttl_seconds=3600)
```

### None (dev/local)
```yaml
auth:
  mode: none
```

---

## Rate limiting

```yaml
policies:
  rate_limit:
    requests_per_minute: 60    # per agent identity
    spend_per_hour_usd: 25.00  # per agent identity
```

Blocked requests get a `retry_after_seconds` field in the error response.

---

## Spending controls

mcp-guard intercepts calls to spending tools (`wallet_request`, `wallet_approve`, `pay_create_checkout`, `wallet_pay`, `x402_pay`) and applies policy:

```yaml
policies:
  max_spend_per_session: 10.00    # hard budget cap per session
  require_approval_above: 2.00    # escalate to approval queue (coming in 0.2.0)
```

Blocked payments return JSON-RPC error code `-32002`.

---

## Audit log

Every intercepted message is logged:

```yaml
policies:
  audit_log: /var/log/mcp-guard.jsonl
```

Each line:
```json
{
  "decision": "allowed",
  "agent_id": "agent-1",
  "method": "tools/call",
  "tool_name": "search_web",
  "session_id": "sess-4f2a",
  "timestamp": 1750000000.0,
  "amount_usd": 0.0,
  "latency_ms": 0.42
}
```

---

## Programmatic use

```python
from mcp_guard import MCPProxy, GuardConfig
from mcp_guard.auth import ApiKeyAuth, create_jwt

config = GuardConfig.from_dict({
    "auth": {"mode": "api_key", "keys": ["sk-abc"]},
    "policies": {"max_spend_per_session": 25.0},
})

proxy = MCPProxy.from_config(config)

# For each incoming JSON-RPC message:
raw = {"jsonrpc": "2.0", "id": 1, "method": "tools/list",
       "params": {"_meta": {"api_key": "sk-abc"}}}

result = proxy.intercept(raw, session_id="sess-abc")
if result.allowed:
    pass  # forward to backend MCP server
else:
    pass  # return result.error_response to client
```

---

## Docker

```bash
docker run -v $(pwd)/mcp-guard.yaml:/config.yaml \
           -v $(pwd)/logs:/var/log \
           bonanzalabs/mcp-guard serve --config /config.yaml
```

*(Docker image coming in 0.2.0)*

---

## EU AI Act compliance

mcp-guard's audit log provides a complete record of every AI agent tool invocation — who called what, when, and with what outcome. Combined with spending controls, this satisfies **Article 14 (human oversight)** requirements under the EU AI Act (enforcement: August 2026).

For managed compliance reports and a hosted dashboard:
→ **[bonanza-labs.com/firewall](https://bonanza-labs.com/firewall)**

---

## License

Apache 2.0. Built by [Bonanza Labs](https://bonanza-labs.com).
