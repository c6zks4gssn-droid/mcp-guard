"""
Scan local MCP client configs for common security issues (no auth, remote URLs, etc.).
"""

from __future__ import annotations

import json
import platform
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ScanFinding:
    severity: str  # critical | warn | info
    source: str
    server_name: str
    message: str


@dataclass
class ScanReport:
    config_path: str
    findings: list[ScanFinding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(f.severity == "critical" for f in self.findings)


def default_config_paths() -> list[Path]:
    home = Path.home()
    system = platform.system()
    paths: list[Path] = []
    if system == "Darwin":
        paths.append(
            home / "Library/Application Support/Claude/claude_desktop_config.json"
        )
        paths.append(home / ".cursor/mcp.json")
    elif system == "Linux":
        paths.append(home / ".config/Claude/claude_desktop_config.json")
        paths.append(home / ".cursor/mcp.json")
    else:
        paths.append(home / ".cursor/mcp.json")
    paths.append(home / ".codeium/windsurf/mcp_config.json")
    return [p for p in paths if p.is_file()]


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _servers_from_config(data: dict[str, Any]) -> dict[str, Any]:
    if "mcpServers" in data:
        return data.get("mcpServers") or {}
    if "servers" in data:
        return data.get("servers") or {}
    return {}


def scan_file(path: Path | str) -> ScanReport:
    p = Path(path).expanduser()
    report = ScanReport(config_path=str(p))
    if not p.is_file():
        report.findings.append(
            ScanFinding("info", str(p), "", "Config file not found (skipped)")
        )
        return report

    try:
        data = _load_json(p)
    except (json.JSONDecodeError, OSError) as e:
        report.findings.append(
            ScanFinding("critical", str(p), "", f"Cannot parse JSON: {e}")
        )
        return report

    servers = _servers_from_config(data)
    if not servers:
        report.findings.append(
            ScanFinding("info", str(p), "", "No mcpServers defined")
        )
        return report

    for name, cfg in servers.items():
        if not isinstance(cfg, dict):
            continue
        cmd = cfg.get("command") or cfg.get("cmd") or ""
        args = cfg.get("args") or []
        url = cfg.get("url") or ""
        env = cfg.get("env") or {}

        if "mcp-guard" in str(cmd) or any("mcp-guard" in str(a) for a in args):
            report.findings.append(
                ScanFinding("info", str(p), name, "Wrapped with mcp-guard — good")
            )

        if url and str(url).startswith(("http://", "https://")):
            if not env.get("MCP_GUARD_API_KEY") and "Authorization" not in str(cfg):
                report.findings.append(
                    ScanFinding(
                        "critical",
                        str(p),
                        name,
                        f"Remote MCP URL without obvious auth: {url}",
                    )
                )

        if cmd and "npx" in str(cmd).lower() and "@modelcontextprotocol" in " ".join(
            map(str, args)
        ):
            report.findings.append(
                ScanFinding(
                    "warn",
                    str(p),
                    name,
                    "Local stdio MCP — ensure filesystem/network scopes are minimal",
                )
            )

        if cmd and not url:
            has_guard = "mcp-guard" in str(cmd) or any(
                "mcp-guard" in str(a) for a in args
            )
            if not has_guard and cfg.get("auth") is None:
                report.findings.append(
                    ScanFinding(
                        "warn",
                        str(p),
                        name,
                        "Direct stdio MCP with no mcp-guard wrapper or auth block",
                    )
                )

    return report


def scan_all(paths: list[Path | str] | None = None) -> list[ScanReport]:
    targets = [Path(p) for p in paths] if paths else default_config_paths()
    if not targets:
        return [
            ScanReport(
                config_path="(none)",
                findings=[
                    ScanFinding(
                        "info",
                        "",
                        "",
                        "No known MCP config files found on this machine",
                    )
                ],
            )
        ]
    return [scan_file(p) for p in targets]


def format_report(reports: list[ScanReport]) -> str:
    lines: list[str] = []
    critical = warn = 0
    for rep in reports:
        lines.append(f"\n📁 {rep.config_path}")
        if not rep.findings:
            lines.append("  ✓ no issues")
            continue
        for f in rep.findings:
            icon = {"critical": "🔴", "warn": "🟡", "info": "ℹ️"}.get(f.severity, "•")
            if f.severity == "critical":
                critical += 1
            if f.severity == "warn":
                warn += 1
            who = f" [{f.server_name}]" if f.server_name else ""
            lines.append(f"  {icon}{who} {f.message}")
    lines.append("")
    lines.append(f"Summary: {critical} critical, {warn} warnings")
    if critical:
        lines.append(
            "Fix: put MCP behind `mcp-guard serve` — "
            "https://github.com/c6zks4gssn-droid/mcp-guard"
        )
    return "\n".join(lines)