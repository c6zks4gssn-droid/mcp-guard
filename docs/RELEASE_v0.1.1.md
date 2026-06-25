## mcp-guard v0.1.1

**Production MCP gateway** — authentication, rate limiting, spending controls, audit logging.

### Install

```bash
pip install "bonanza-mcp-guard[yaml]"
```

### Commands

- `mcp-guard scan` — audit Claude Desktop, Cursor, Windsurf MCP configs
- `mcp-guard serve --config mcp-guard.yaml` — stdio gateway in front of your MCP server

### PyPI

Package name: `bonanza-mcp-guard` (PyPI collision on `mcp-guard`). CLI entry point: `mcp-guard`.

### Links

- Docs: [README](https://github.com/c6zks4gssn-droid/mcp-guard#readme)
- Issues: https://github.com/c6zks4gssn-droid/mcp-guard/issues