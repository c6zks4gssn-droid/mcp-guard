"""mcp-guard CLI: serve (stdio gateway) and scan (local config audit)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid

from .config import GuardConfig
from .proxy import MCPProxy
from .scan import format_report, scan_all, scan_file
from .http_transport import run_http_server
from .approval_store import SQLiteApprovalQueue
from .approvals_cli import cmd_approvals_list, cmd_approvals_approve, cmd_approvals_deny


def _load_config(path: str) -> GuardConfig:
    if path.endswith((".yaml", ".yml")):
        return GuardConfig.from_yaml(path)
    with open(path, encoding="utf-8") as f:
        return GuardConfig.from_dict(json.load(f))


def cmd_serve(config_path: str, server: str | None) -> int:
    config = _load_config(config_path)
    if not config.servers:
        print("mcp-guard: no servers in config", file=sys.stderr)
        return 2

    chosen = None
    if server:
        for s in config.servers:
            if s.name == server:
                chosen = s
                break
        if not chosen:
            names = ", ".join(s.name for s in config.servers)
            print(
                f"mcp-guard: unknown server {server!r} (have: {names})",
                file=sys.stderr,
            )
            return 2
    else:
        chosen = config.servers[0]

    proxy = MCPProxy.from_config(config)
    session_id = os.environ.get("MCP_GUARD_SESSION_ID") or str(uuid.uuid4())[:12]

    env = {**os.environ, **chosen.env}
    proc = subprocess.Popen(
        [chosen.command, *chosen.args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
        bufsize=1,
    )

    assert proc.stdin and proc.stdout

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            print(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": "Parse error"},
                    }
                ),
                flush=True,
            )
            continue

        result = proxy.intercept(raw, session_id=session_id)
        if not result.allowed and result.error_response is not None:
            print(json.dumps(result.error_response), flush=True)
            continue

        proc.stdin.write(line + "\n")
        proc.stdin.flush()
        out_line = proc.stdout.readline()
        if out_line:
            sys.stdout.write(out_line)
            sys.stdout.flush()

    return 0


def cmd_scan(paths: list[str] | None) -> int:
    if paths:
        reports = [scan_file(p) for p in paths]
    else:
        reports = scan_all()
    print(format_report(reports))
    return 1 if any(not r.ok for r in reports) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mcp-guard",
        description="Production MCP gateway: auth, rate limits, spend caps, audit log",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    serve_p = sub.add_parser("serve", help="Run stdio gateway in front of an MCP server")
    serve_p.add_argument("--config", "-c", required=True, help="Path to mcp-guard.yaml")
    serve_p.add_argument(
        "--server",
        "-s",
        default=None,
        help="Named server from config (default: first)",
    )

    http_p = sub.add_parser("serve-http", help="Run HTTP/SSE gateway (remote agents)")
    http_p.add_argument("--config", "-c", required=True, help="Path to mcp-guard.yaml")
    http_p.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    http_p.add_argument("--port", "-p", type=int, default=8080, help="Port (default: 8080)")
    http_p.add_argument("--server", "-s", default=None, help="Named server from config")

    scan_p = sub.add_parser("scan", help="Audit local MCP client configs")
    scan_p.add_argument(
        "paths",
        nargs="*",
        help="Config files (default: Claude Desktop, Cursor, Windsurf paths)",
    )

    approvals_p = sub.add_parser("approvals", help="Manage approval requests")
    approvals_p.add_argument("--db", default="~/.mcp-guard/approvals.db", help="SQLite path")
    approvals_sub = approvals_p.add_subparsers(dest="approvals_command", required=True)
    approvals_sub.add_parser("list", help="List pending (and recently decided)")
    ap_p = approvals_sub.add_parser("approve", help="Approve a request")
    ap_p.add_argument("req_id", help="Approval request ID (full or short prefix)")
    ap_p.add_argument("--by", default="admin", help="Decider name")
    dn_p = approvals_sub.add_parser("deny", help="Deny a request")
    dn_p.add_argument("req_id", help="Approval request ID (full or short prefix)")
    dn_p.add_argument("--by", default="admin", help="Decider name")
    dn_p.add_argument("--reason", default="", help="Reason for denial")
    approvals_p.add_argument("--show-decided", action="store_true", help="Show recent decided (with list)")

    args = parser.parse_args(argv)
    if args.command == "serve":
        return cmd_serve(args.config, args.server)
    if args.command == "serve-http":
        config = _load_config(args.config)
        return run_http_server(config, host=args.host, port=args.port, server_name=args.server)
    if args.command == "scan":
        return cmd_scan(args.paths or None)
    if args.command == "approvals":
        db_path = os.path.expanduser(args.db)
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        if args.approvals_command == "list":
            return cmd_approvals_list(db_path, show_decided=args.show_decided)
        if args.approvals_command == "approve":
            return cmd_approvals_approve(db_path, args.req_id, args.by)
        if args.approvals_command == "deny":
            return cmd_approvals_deny(db_path, args.req_id, args.by, args.reason)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())