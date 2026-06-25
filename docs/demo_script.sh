#!/bin/bash
# Simulated mcp-guard demo for asciinema recording
# Recorded with: asciinema rec --idle-time-limit=0.5 docs/demo.cast -c "bash docs/demo_script.sh"

echo '$ mcp-guard scan'

sleep 0.5

echo ""
echo '📁 ~/Library/Application Support/Claude/claude_desktop_config.json'
echo '  ℹ️ No mcpServers defined'
echo ""
sleep 0.3
echo '📁 ~/.cursor/mcp.json'
echo '  🟡 [filesystem] Direct stdio MCP with no mcp-guard wrapper or auth block'
echo '  🔴 [remote-fetch] Remote MCP URL without obvious auth: https://api.example.com/mcp'
echo ""
sleep 0.3
echo 'Summary: 1 critical, 1 warnings'
echo 'Fix: put MCP behind `mcp-guard serve` — https://github.com/c6zks4gssn-droid/mcp-guard'
echo ""
sleep 0.5

echo '$ mcp-guard serve --config examples/minimal.yaml'
sleep 0.5
echo ''
echo '  mcp-guard v0.1.1  ·  gateway started'
echo '  ────────────────────────────────────'
echo '  auth:      api_key (1 key loaded)'
echo '  rate limit: 30 req/min'
echo '  spend cap:  $5.00/session'
echo '  audit:      /var/log/mcp-guard.jsonl'
echo '  ────────────────────────────────────'
echo '  → proxying to: echo (python3)'
echo ''
sleep 0.5
echo '  ✓ Ready. Agents connect via stdio.'
echo ''
sleep 1