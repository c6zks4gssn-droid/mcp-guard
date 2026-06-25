# mcp-guard launch — copy-paste per kanaal

## X Thread (5 posts)

### Post 1 — Hook
```
1,800+ MCP servers exposed on the internet with zero authentication.

Any AI agent can call tools — no identity, no rate limit, no audit trail.

I built mcp-guard to fix that. 🧵

github.com/c6zks4gssn-droid/mcp-guard
```

### Post 2 — How it works
```
mcp-guard sits between your MCP client (Claude Desktop, Cursor, Windsurf) and your MCP server.

Drop-in replacement — zero code changes to your server.

API-key auth · JWT · rate limits · spend caps · JSONL audit logs
```

### Post 3 — 30 second try
```
Try it now:

pip install "bonanza-mcp-guard[yaml]"
mcp-guard scan        # audit your local MCP configs
mcp-guard serve -c mcp-guard.yaml

Zero required dependencies.
```

### Post 4 — Config snippet
```
mcp-guard.yaml:

auth:
  mode: api_key
  keys: ["sk-agent-1"]
policies:
  rate_limit:
    requests_per_minute: 60
  max_spend_per_session: 10.00
  audit_log: /var/log/mcp-guard.jsonl

That's it. Your MCP server is now protected.
```

### Post 5 — Links
```
GitHub: github.com/c6zks4gssn-droid/mcp-guard
PyPI: pypi.org/project/bonanza-mcp-guard/

Apache-2.0 · solo maintainer · Bonanza Labs

If you build MCP servers or agents — try it and let me know what's missing. 🙏

#MCP #AI #Security #ModelContextProtocol
```

---

## Reddit — r/MCP

**Title:** mcp-guard — auth, rate limits, and spend caps in front of any MCP server (open source)

**Body:**
```
I built a stdio gateway that sits between your MCP client and server, adding:

- API-key or JWT authentication
- Per-agent rate limiting
- Spending caps (wallet/x402 tools)
- JSONL audit logs

Zero required dependencies. Drop it in your Claude Desktop / Cursor config:

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

Install:
```
pip install "bonanza-mcp-guard[yaml]"
mcp-guard scan          # audit your existing MCP configs
mcp-guard serve -c mcp-guard.yaml
```

Also includes a GitHub Action that scans MCP config files on PRs for security issues.

GitHub: https://github.com/c6zks4gssn-droid/mcp-guard
PyPI: https://pypi.org/project/bonanza-mcp-guard/

Apache-2.0, solo maintainer. Feedback welcome — especially on which auth mode you'd use in production.
```

---

## Reddit — r/ClaudeAI

**Title:** Secure your Claude Desktop MCP servers with mcp-guard (open source, pip install)

**Body:**
```
If you're using MCP servers with Claude Desktop, you might want auth and rate limiting on top.

mcp-guard is a drop-in gateway — Claude talks to mcp-guard, mcp-guard talks to your real server:

```json
{
  "mcpServers": {
    "guarded": {
      "command": "mcp-guard",
      "args": ["serve", "--config", "mcp-guard.yaml"]
    }
  }
}
```

Features: API-key/JWT auth, rate limits, spend caps, audit logs. Zero deps.

```
pip install "bonanza-mcp-guard[yaml]"
mcp-guard scan   # audit what you have now
```

GitHub: https://github.com/c6zks4gssn-droid/mcp-guard
PyPI: https://pypi.org/project/bonanza-mcp-guard/

Apache-2.0. Would love feedback from Claude Desktop power users.
```

---

## Reddit — r/LocalLLaMA

**Title:** mcp-guard: add auth, rate limits, and spend caps to any MCP server (Python, zero deps)

**Body:**
```
Built a stdio gateway for MCP servers — works with any MCP client (Claude Desktop, Cursor, Windsurf, custom agents).

- API-key / JWT auth
- Per-agent rate limiting (requests/min, spend/hour)
- Spend caps on wallet/x402 payment tools
- JSONL audit trail
- Zero required dependencies
- GitHub Action for scanning MCP configs on PRs

```
pip install "bonanza-mcp-guard[yaml]"
mcp-guard scan
mcp-guard serve -c mcp-guard.yaml
```

GitHub: https://github.com/c6zks4gssn-droid/mcp-guard
PyPI: https://pypi.org/project/bonanza-mcp-guard/

Apache-2.0, solo dev. Especially interested in feedback from people running local MCP servers with Ollama/custom agents.
```

---

## Dev.to Article

**Title:** Securing MCP Servers with mcp-guard

**Body:**
```markdown
# Securing MCP Servers with mcp-guard

Security research in 2026 found **1,800+ internet-exposed MCP endpoints** with **no authentication**. Any AI agent can invoke tools with no identity, no spend ceiling, and no audit trail.

That's a problem.

## The fix

[mcp-guard](https://github.com/c6zks4gssn-droid/mcp-guard) is a stdio gateway that sits between your MCP client and your MCP server:

```
Agent → mcp-guard → your MCP server
```

It adds:
- **Auth** — API-key or JWT
- **Rate limiting** — requests per minute, spend per hour
- **Spend caps** — block payments above a threshold
- **Audit logs** — JSONL, every request logged

Zero required dependencies. Apache-2.0.

## 30-second try

```bash
pip install "bonanza-mcp-guard[yaml]"
mcp-guard scan          # audit your existing MCP configs
mcp-guard serve -c mcp-guard.yaml
```

## Wire into Claude Desktop

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

## Config

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

## GitHub Action

The repo includes a GitHub Action that scans MCP config files in PRs for security issues — missing auth, exposed remote URLs, no guard wrapper. Fails PRs with critical findings and posts a comment with the report.

```yaml
uses: c6zks4gssn-droid/mcp-guard/.github/workflows/mcp-scan.yml@main
```

## Links

- [GitHub](https://github.com/c6zks4gssn-droid/mcp-guard)
- [PyPI](https://pypi.org/project/bonanza-mcp-guard/)
- [Release v0.1.1](https://github.com/c6zks4gssn-droid/mcp-guard/releases/tag/v0.1.1)

Apache-2.0 · Bonanza Labs

---

*Feedback welcome — especially on which auth mode you'd use in production.*
```

---

## Awesome-list PRs

### awesome-mcp-servers
```
## Submit PR to: https://github.com/punkpeye/awesome-mcp-servers

Add to Security section:

- [mcp-guard](https://github.com/c6zks4gssn-droid/mcp-guard) — Security gateway for MCP servers: API-key/JWT auth, rate limiting, spend caps, audit logs. Zero deps. `pip install bonanza-mcp-guard`
```

### awesome-model-context-protocol
```
## Submit PR to: https://github.com/anaisbetts/awesome-model-context-protocol

Add to Tools/Security:

- [mcp-guard](https://github.com/c6zks4gssn-droid/mcp-guard) — Auth, rate limits, spend caps, and audit logs in front of any MCP server. `pip install bonanza-mcp-guard`
```