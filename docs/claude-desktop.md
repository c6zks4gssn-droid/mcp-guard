# Claude Desktop

Use **mcp-guard** as the MCP server command; point it at a YAML config that lists your real backend under `servers:`.

```json
{
  "mcpServers": {
    "guarded-fs": {
      "command": "mcp-guard",
      "args": ["serve", "--config", "/absolute/path/to/mcp-guard.yaml", "--server", "filesystem"]
    }
  }
}
```

Set `MCP_GUARD_API_KEY` in the environment (or use JWT mode in YAML).

Run `mcp-guard scan` to audit `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS.