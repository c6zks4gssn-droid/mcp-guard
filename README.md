# mcp-guard

[![CI](https://github.com/c6zks4gssn-droid/mcp-guard/actions/workflows/ci.yml/badge.svg)](https://github.com/c6zks4gssn-droid/mcp-guard/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/bonanza-mcp-guard)](https://pypi.org/project/bonanza-mcp-guard/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/pypi/pyversions/bonanza-mcp-guard)](https://pypi.org/project/bonanza-mcp-guard/)

**Put auth, rate limits, spend caps, and audit logs in front of any MCP server — without changing the server.**

```bash
pip install "bonanza-mcp-guard[yaml]"
mcp-guard scan
mcp-guard serve --config mcp-guard.yaml
```

> **PyPI:** package [`bonanza-mcp-guard`](https://pypi.org/project/bonanza-mcp-guard/) (name `mcp-guard` was taken). CLI is still `mcp-guard`.

![Demo](docs/demo.gif)

Sits in front of any MCP server over stdio. Zero required dependencies.

Complements static scanners like [mcp-scan](https://github.com/invariantlabs-ai/mcp-scan) with a **runtime stdio gateway** (auth, limits, audit).

## Why mcp-guard?

| Without mcp-guard | With mcp-guard |
|---|---|
| Any agent calls any tool | Agent must authenticate (API key / JWT) |
| No spend ceiling | Per-session spend caps, per-hour rate limits |
| No audit trail | Every request logged to JSONL |
| Server exposed directly | Gateway wraps server — zero code changes |

Complements static scanners like [mcp-scan](https://github.com/invariantlabs-ai/mcp-scan) with a **runtime stdio gateway** (auth, limits, audit).

---

## The problem

Security research in 2026 reported **1,800+ internet-exposed MCP endpoints** with **no authentication**. Any MCP client can invoke tools with no identity, no spend ceiling, and no audit trail.

`mcp-guard` adds a gateway layer — Claude Desktop, Cursor, Windsurf, or custom agents talk to `mcp-guard`; it talks to your real MCP server.

---

## 30-second try

```bash
pip install "bonanza-mcp-guard[yaml]"
mcp-guard scan
```

Example output:

```
📁 ~/Library/Application Support/Claude/claude_desktop_config.json
  ℹ️ No mcpServers defined

Summary: 0 critical, 0 warnings
```

Then add a config and run the gateway:

```bash
mcp-guard serve --config mcp-guard.yaml
```

Wire into Claude Desktop:

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

---

## Quickstart

**1. Install**

```bash
pip install "bonanza-mcp-guard[yaml]"
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
    - "sk-agent-1"
    - "sk-agent-2"

servers:
  filesystem:
    command: npx @modelcontextprotocol/server-filesystem /data

policies:
  max_spend_per_session: 10.00
  audit_log: /var/log/mcp-guard.jsonl
  rate_limit:
    requests_per_minute: 100
    spend_per_hour_usd: 50.00
```

**3. Agents include auth in requests**

```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "_meta": { "api_key": "sk-agent-1" },
    "name": "wallet_request",
    "arguments": { "amount": 1.50 }
  }
}
```

---

## Architecture

```
MCP Client (Claude Desktop / Cursor / custom agent)
    │
    ▼  JSON-RPC over stdio
┌──────────────┐
│  mcp-guard   │  auth → rate limit → spend check → audit
└──────────────┘
    │
    ▼  forwards allowed requests
Your MCP Server (filesystem, wallet, fetch, anything)
```

**1,168 lines of Python. Zero required dependencies.**

---

## Config reference

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `auth.mode` | `none` \| `api_key` \| `jwt` | `none` | Authentication mode |
| `auth.keys` | `list[str]` | `[]` | Valid API keys (mode=api_key) |
| `auth.jwt_secret` | `str` | — | HMAC-SHA256 secret (mode=jwt) |
| `policies.rate_limit.requests_per_minute` | `int` | `∞` | Max requests per agent per minute |
| `policies.rate_limit.spend_per_hour_usd` | `float` | `∞` | Max spend per agent per hour |
| `policies.max_spend_per_session` | `float` | `∞` | Session spend cap |
| `policies.require_approval_above` | `float` | `∞` | Threshold for manual approval |
| `policies.audit_log` | `str` | — | JSONL audit log path |
| `servers` | `map` | `{}` | Backend MCP servers to proxy to |

---

## Authentication modes

### API Key (simplest)

```yaml
auth:
  mode: api_key
  keys:
    - "sk-agent-1"
```

Keys: `_meta.api_key`, `_meta.token`, `Authorization: Bearer`, or `X-API-Key`.

### JWT (multi-agent)

```yaml
auth:
  mode: jwt
  jwt_secret: "${JWT_SECRET}"
```

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

## Rate limiting & spending

```yaml
policies:
  rate_limit:
    requests_per_minute: 60
    spend_per_hour_usd: 25.00
  max_spend_per_session: 10.00
  require_approval_above: 2.00
```

Spending tools: `wallet_request`, `wallet_pay`, `x402_pay`, etc. Blocked payments: JSON-RPC `-32002`.

Use with **[agent-budget](https://github.com/c6zks4gssn-droid/agent-budget)** (`pip install bonanza-labs-agent-budget`) for `@budget` on LLM calls.

---

## Audit log

```yaml
policies:
  audit_log: /var/log/mcp-guard.jsonl
```

---

## Programmatic use

```python
from mcp_guard import MCPProxy, GuardConfig

config = GuardConfig.from_dict({
    "auth": {"mode": "api_key", "keys": ["sk-abc"]},
    "policies": {"max_spend_per_session": 25.0},
})
proxy = MCPProxy.from_config(config)
```

---

## Related (Bonanza Labs)

| Project | Role |
|---------|------|
| [agent-budget](https://github.com/c6zks4gssn-droid/agent-budget) | `@budget(max_usd=…)` for LLM + x402 |
| [bonanza-labs-fork-doctor](https://github.com/c6zks4gssn-droid/bonanza-labs-fork-doctor) | Repo health before you ship |

---

## GitHub Action — scan MCP configs on PRs

Automatically scan MCP config files in pull requests for security issues (missing auth, exposed remote URLs, no guard wrapper).

```yaml
# .github/workflows/mcp-scan.yml — already included in this repo
# Triggers on: **/claude_desktop_config.json, **/mcp.json, **/*mcp*.json/yaml
```

Add it to your repo:
```yaml
uses: c6zks4gssn-droid/mcp-guard/.github/workflows/mcp-scan.yml@main
```

Or copy the workflow file directly. Fails PRs with critical findings and posts a comment with the full report.

---

## Roadmap

### v0.1.2 (next)
- [x] Docker image (`docker run mcp-guard`)
- [ ] Approval queue — hold tool calls above threshold for human approval
- [ ] HTTP/SSE transport (not just stdio)
- [ ] Tool allowlist/denylist per agent
- [ ] Prometheus metrics endpoint

### Future
- [ ] Standalone GitHub Action (reusable workflow)
- [ ] Web dashboard for audit log visualization
- [ ] Multi-server routing (one gateway, many backends)
- [ ] OAuth2 provider for agent-to-agent auth
- [ ] Plugin system for custom policy checks

**Launch:** [LAUNCH.md](LAUNCH.md)

---

## Docker

```bash
# Build
DOCKER_BUILDKIT=1 docker build -t mcp-guard .

# Run with config
DOCKER_BUILDKIT=1 docker run --rm -i \
  -v $(pwd)/mcp-guard.yaml:/etc/mcp-guard/config.yaml:ro \
  -v $(pwd)/logs:/var/log/mcp-guard \
  mcp-guard serve --config /etc/mcp-guard/config.yaml
```

Or with docker compose:
```bash
docker compose up
```

CI publishes to `ghcr.io/c6zks4gssn-droid/mcp-guard` on every tag.

---

## Contributing

PRs welcome. The codebase is 1,168 lines across 8 modules — small enough to hold in your head.

```bash
git clone https://github.com/c6zks4gssn-droid/mcp-guard
cd mcp-guard
pip install -e ".[yaml,dev]"
pytest
```

### Project structure

```
mcp_guard/
├── __main__.py    # CLI entry point (serve, scan)
├── config.py      # GuardConfig + YAML/JSON loader
├── auth.py        # API key + JWT providers
├── proxy.py       # MCPProxy — the intercept engine
├── ratelimit.py   # Per-agent rate limiting
├── audit.py       # JSONL audit logger
└── scan.py        # Local config scanner
```

---

## License

Apache 2.0 · [Bonanza Labs](https://bonanza-labs.com)