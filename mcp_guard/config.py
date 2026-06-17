"""
Configuration parsing for mcp-guard.

Example mcp-guard.yaml:

    auth:
      mode: api_key           # "api_key" | "jwt" | "none"
      keys:
        - "sk-agent-abc123"
        - "sk-agent-def456"
      jwt_secret: "${JWT_SECRET}"   # for jwt mode

    servers:
      bonanza:
        command: bonanza-mcp serve
        env:
          BONANZA_API_KEY: "${BONANZA_API_KEY}"
      filesystem:
        command: npx @modelcontextprotocol/server-filesystem /data

    policies:
      max_spend_per_session: 10.00
      require_approval_above: 2.00
      block_vendors:
        - "untrusted.com"
      audit_log: /var/log/mcp-guard.jsonl
      rate_limit:
        requests_per_minute: 100
        spend_per_hour_usd: 50.00
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class AuthConfig:
    mode: Literal["none", "api_key", "jwt"] = "none"
    keys: list[str] = field(default_factory=list)
    jwt_secret: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "AuthConfig":
        return cls(
            mode=d.get("mode", "none"),
            keys=[_expand(k) for k in d.get("keys", [])],
            jwt_secret=_expand(d.get("jwt_secret", "")),
        )


@dataclass
class RateLimitConfig:
    requests_per_minute: int = 0       # 0 = unlimited
    spend_per_hour_usd: float = 0.0    # 0 = unlimited

    @classmethod
    def from_dict(cls, d: dict) -> "RateLimitConfig":
        return cls(
            requests_per_minute=int(d.get("requests_per_minute", 0)),
            spend_per_hour_usd=float(d.get("spend_per_hour_usd", 0.0)),
        )


@dataclass
class PolicyConfig:
    max_spend_per_session: float = float("inf")
    require_approval_above: float | None = None
    block_vendors: list[str] = field(default_factory=list)
    allow_vendors: list[str] | None = None
    audit_log: str | None = None
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)

    @classmethod
    def from_dict(cls, d: dict) -> "PolicyConfig":
        return cls(
            max_spend_per_session=float(d.get("max_spend_per_session", float("inf"))),
            require_approval_above=(
                float(d["require_approval_above"]) if "require_approval_above" in d else None
            ),
            block_vendors=list(d.get("block_vendors", [])),
            allow_vendors=list(d["allow_vendors"]) if "allow_vendors" in d else None,
            audit_log=d.get("audit_log"),
            rate_limit=RateLimitConfig.from_dict(d.get("rate_limit", {})),
        )


@dataclass
class ServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, name: str, d: dict) -> "ServerConfig":
        # command may be "npx foo bar" — split it
        parts = d.get("command", "").split()
        cmd = parts[0] if parts else ""
        args = parts[1:] + list(d.get("args", []))
        return cls(
            name=name,
            command=cmd,
            args=args,
            env={k: _expand(v) for k, v in d.get("env", {}).items()},
        )


@dataclass
class GuardConfig:
    auth: AuthConfig = field(default_factory=AuthConfig)
    servers: list[ServerConfig] = field(default_factory=list)
    policies: PolicyConfig = field(default_factory=PolicyConfig)

    @classmethod
    def from_dict(cls, d: dict) -> "GuardConfig":
        servers = [
            ServerConfig.from_dict(name, cfg)
            for name, cfg in d.get("servers", {}).items()
        ]
        return cls(
            auth=AuthConfig.from_dict(d.get("auth", {})),
            servers=servers,
            policies=PolicyConfig.from_dict(d.get("policies", {})),
        )

    @classmethod
    def from_yaml(cls, path: str) -> "GuardConfig":
        try:
            import yaml
            with open(path) as f:
                return cls.from_dict(yaml.safe_load(f) or {})
        except ImportError:
            raise RuntimeError(
                "pyyaml is required to load YAML config: pip install mcp-guard[yaml]"
            )

    @classmethod
    def from_dict_no_yaml(cls, d: dict) -> "GuardConfig":
        """Alias for tests — same as from_dict."""
        return cls.from_dict(d)


def _expand(value: str) -> str:
    """Expand ${ENV_VAR} placeholders."""
    return re.sub(
        r"\$\{([^}]+)\}",
        lambda m: os.environ.get(m.group(1), m.group(0)),
        value,
    )
