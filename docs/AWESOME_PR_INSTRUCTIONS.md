## PR title
Add bonanza-mcp-guard — lightweight stdio MCP gateway (auth, rate limits, spend caps)

## PR body (paste into GitHub PR description)

### bonanza-mcp-guard / [mcp-guard](https://github.com/c6zks4gssn-droid/mcp-guard)

Lightweight **stdio MCP gateway** for Claude Desktop, Cursor, and custom agents — not a K8s/Docker registry stack.

- **Auth:** API keys or JWT on tool calls
- **Rate limits:** per-agent requests / spend per hour
- **Spend caps:** intercepts wallet/x402-style payment tools
- **Audit:** JSONL log of every invocation
- **Local audit:** `mcp-guard scan` for MCP client configs

```bash
pip install "bonanza-mcp-guard[yaml]"
mcp-guard scan
mcp-guard serve --config mcp-guard.yaml
```

PyPI: [bonanza-mcp-guard](https://pypi.org/project/bonanza-mcp-guard/) (CLI: `mcp-guard`)

Complements static scanners (e.g. [mcp-scan](https://github.com/invariantlabs-ai/mcp-scan)) with a **runtime proxy**.

Apache-2.0.

---

## Where to open PR

1. **Primary:** https://github.com/e2b-dev/awesome-mcp-gateways — fork, add row in README table/list following their format
2. **Secondary:** https://github.com/punkpeye/awesome-mcp-devtools — security/gateway section if present

## Steps

```bash
gh repo fork e2b-dev/awesome-mcp-gateways --clone
cd awesome-mcp-gateways
# edit README — copy style of existing entries
git checkout -b add-bonanza-mcp-guard
git commit -am "Add bonanza-mcp-guard stdio gateway"
git push -u origin add-bonanza-mcp-guard
gh pr create --title "Add bonanza-mcp-guard" --body-file ~/bonanza-oss/mcp-guard/docs/AWESOME_PR_BODY.md
```