# mcp-guard launch playbook

## Pre-flight (done / you)

- [x] PyPI: `bonanza-mcp-guard` 0.1.1
- [x] GitHub `main` green CI
- [ ] Profile: **pin** `mcp-guard` on https://github.com/c6zks4gssn-droid
- [ ] Bio: `MCP gateway — auth, rate limits, spend caps. pip install bonanza-mcp-guard`
- [ ] Topics on repo (run below or GitHub UI)
- [ ] Terminal GIF in README (`docs/demo.gif`) — record with asciinema or Cleanshot
- [ ] GitHub Release `v0.1.1` (script at bottom)

### Set topics (CLI)

```bash
gh repo edit c6zks4gssn-droid/mcp-guard \
  --add-topic mcp --add-topic model-context-protocol --add-topic security \
  --add-topic ai-agents --add-topic claude --add-topic cursor
```

### Release tag

```bash
cd ~/bonanza-oss/mcp-guard
git tag -a v0.1.1 -m "v0.1.1 — scan + serve, PyPI bonanza-mcp-guard" 2>/dev/null || true
git push origin v0.1.1
gh release create v0.1.1 --title "v0.1.1" --notes-file docs/RELEASE_v0.1.1.md
```

---

## Show HN (Tuesday 08:00–10:00 US Eastern)

**Title (pick one):**

1. `Show HN: mcp-guard – auth, rate limits and spend caps in front of any MCP server`
2. `Show HN: Audit Claude/Cursor MCP configs in one command (mcp-guard scan)`

**Body:**

```
I built mcp-guard after reading that most internet-exposed MCP servers had no authentication — agents can call tools with no identity and no audit trail.

mcp-guard is a stdio gateway: drop it in Claude Desktop / Cursor config, point at your real MCP server, and get API-key or JWT auth, per-agent rate limits, spend caps on wallet/x402 tools, and JSONL audit logs. Zero required deps.

Try in 30 seconds:

  pip install "bonanza-mcp-guard[yaml]"
  mcp-guard scan          # audit local MCP client configs
  mcp-guard serve -c mcp-guard.yaml

PyPI name is bonanza-mcp-guard (mcp-guard was taken on PyPI); CLI is still mcp-guard.

GitHub: https://github.com/c6zks4gssn-droid/mcp-guard
PyPI: https://pypi.org/project/bonanza-mcp-guard/

Would love feedback on: (1) which auth mode you’d use in prod, (2) whether a GitHub Action for MCP config scanning on PRs is useful.
```

**First comment (post immediately):** link to `docs/claude-desktop.md` if present, or Quickstart in README; mention Apache-2.0, solo maintainer, Bonanza Labs.

---

## X thread (5 posts)

1. Hook + stat (1862 exposed MCP / no auth narrative from README)
2. `pip install` + `mcp-guard scan` screenshot
3. YAML snippet (auth + rate_limit only)
4. Claude Desktop JSON one-liner
5. GitHub + PyPI links; ask for retweet from MCP/OpenClaw accounts

---

## Awesome-list PRs (after HN)

- Search: `awesome-mcp`, `awesome-model-context-protocol`, `awesome-ai-agents`
- One paragraph + link; do not spam 10 lists same day

---

## Metrics (week 1)

| Metric | Target |
|--------|--------|
| GitHub stars | 50+ realistic, 200+ stretch |
| PyPI downloads | track on pypi.org/project/bonanza-mcp-guard |
| HN points | 10+ = worth follow-up comment |

## Do not

- Launch `agent-budget` or `fork-doctor` same week (split attention)
- Promise EU AI Act compliance as legal advice (keep “audit trail helps oversight” only)