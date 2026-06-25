# Changelog

All notable changes to mcp-guard will be documented in this file.

## [0.1.3] — 2026-06-25

### Added
- **Persistent approval queue** (`mcp_guard/approval_store.py`) — SQLite backend survives restarts
- **Approval CLI** — `mcp-guard approvals list/approve/deny`
  - Short ID prefixes supported (`abc123` matches full UUID)
  - `--show-decided` flag for recent history
- **Proxy holds spending tool calls** for human approval when amount ≥ `require_approval_above` (error code -32004)
  - Returns approval_id in error response data so clients can poll
- **`policies.approval_db`** — custom SQLite path (default `~/.mcp-guard/approvals.db`)

### Changed
- Version: 0.1.2 → 0.1.3
- Tests: 48 → 61 (13 new for v0.1.3 features)

## [0.1.2] — 2026-06-25

### Added
- **Tool allowlist/denylist** — restrict which tools agents can call (error code -32003)
- **Approval queue** (`mcp_guard/approval.py`) — hold tool calls above threshold for human approval
  - request → approve/deny/expire flow
  - TTL-based auto-expiry (default 300s)
  - In-memory backend (Redis/SQLite planned)
- **Docker image** — `docker run mcp-guard` with Dockerfile + docker-compose.yml
  - CI auto-publishes to `ghcr.io/c6zks4gssn-droid/mcp-guard` on tag
- **HTTP/SSE transport** — `mcp-guard serve-http --port 8080`
  - `POST /rpc` — JSON-RPC over HTTP
  - `GET /health` — health check
  - `GET /metrics` — Prometheus metrics
  - Auth via `X-API-Key` or `Authorization: Bearer` headers
- **Prometheus metrics** — requests_total, blocked_total, allowed_total, spend_total

### Changed
- README: added "Why mcp-guard?" comparison table, architecture diagram, config reference, contributing section, Docker section, HTTP/SSE section
- Version: 0.1.1 → 0.1.2
- Tests: 30 → 48 (18 new for v0.1.2 features)

## [0.1.1] — 2026-06-25

### Added
- Initial release
- API-key and JWT authentication
- Per-agent rate limiting (requests/min, spend/hour)
- Session spend caps
- JSONL audit logging
- `mcp-guard scan` — audit local MCP client configs
- `mcp-guard serve` — stdio gateway
- GitHub Action for scanning MCP configs on PRs
- Zero required dependencies
- PyPI package: `bonanza-mcp-guard`