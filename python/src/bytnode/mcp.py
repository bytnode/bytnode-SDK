"""Plug the BytNode MCP server into an AI client (Claude, Cursor, VS Code, Windsurf).

    bytnode mcp install cursor            # from the command line
    bytnode.mcp.install("claude-desktop") # from Python

The MCP server (`https://api.bytnode.com/mcp`, Streamable HTTP) gives an agent three tools —
system info, market data (latest or dated history) and indicators — with your key. The
config file is merged, never replaced: a backup is written next to it first.
"""

from __future__ import annotations

import json
import os
import platform
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ._errors import MissingAPIKeyError

MCP_URL = "https://api.bytnode.com/mcp"
SERVER_NAME = "bytnode"

McpClient = Literal["claude-desktop", "claude-code", "cursor", "vscode", "windsurf"]
CLIENTS: tuple[McpClient, ...] = ("claude-desktop", "claude-code", "cursor", "vscode", "windsurf")


def _key(api_key: str | None) -> str:
    key = api_key or os.environ.get("BYTNODE_API_KEY")
    if not key:
        raise MissingAPIKeyError()
    return key.strip()


def mask(key: str) -> str:
    """`cb_live_abcd...wxyz`: enough to recognise a key, not enough to use it."""
    return "***" if len(key) < 16 else f"{key[:12]}...{key[-4:]}"


def server_entry(client: McpClient, api_key: str, url: str = MCP_URL) -> dict[str, Any]:
    """The `bytnode` entry of the client's MCP configuration."""
    if client == "cursor":
        return {"url": url, "headers": {"X-API-KEY": api_key}}
    if client == "windsurf":
        return {"serverUrl": url, "headers": {"X-API-KEY": api_key}}
    if client == "vscode":
        return {"type": "http", "url": url, "headers": {"X-API-KEY": api_key}}
    if client == "claude-desktop":
        # Claude Desktop's config file only starts local processes: `mcp-remote` bridges to
        # the remote server. No space after the colon: it would be split on Windows.
        return {
            "command": "npx",
            "args": ["-y", "mcp-remote", url, "--header", "X-API-KEY:${BYTNODE_API_KEY}"],
            "env": {"BYTNODE_API_KEY": api_key},
        }
    if client == "claude-code":
        return {"type": "http", "url": url, "headers": {"X-API-KEY": api_key}}
    raise ValueError(f"unknown MCP client {client!r}: one of {', '.join(CLIENTS)}")


def config_path(client: McpClient) -> Path | None:
    """Where the client keeps its MCP servers (`None` for Claude Code: it has a command)."""
    home = Path.home()
    system = platform.system()
    if client == "claude-desktop":
        if system == "Windows":
            return (
                Path(os.environ.get("APPDATA", home / "AppData" / "Roaming")) / "Claude" / "claude_desktop_config.json"
            )
        if system == "Darwin":
            return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        return home / ".config" / "Claude" / "claude_desktop_config.json"
    if client == "cursor":
        return home / ".cursor" / "mcp.json"
    if client == "windsurf":
        return home / ".codeium" / "windsurf" / "mcp_config.json"
    if client == "vscode":
        return Path.cwd() / ".vscode" / "mcp.json"  # the workspace of the current directory
    return None


def claude_code_command(api_key: str, url: str = MCP_URL, scope: str = "user") -> list[str]:
    return [
        "claude",
        "mcp",
        "add",
        "--transport",
        "http",
        "--scope",
        scope,
        SERVER_NAME,
        url,
        "--header",
        f"X-API-KEY: {api_key}",
    ]


@dataclass
class InstallResult:
    client: str
    path: Path | None = None
    backup: Path | None = None
    command: list[str] = field(default_factory=list)
    ran: bool = False
    dry_run: bool = False
    content: dict[str, Any] = field(default_factory=dict)

    def describe(self) -> str:
        if self.command:
            prefix = "X-API-KEY: "
            shown = [prefix + mask(a[len(prefix) :]) if a.startswith(prefix) else a for a in self.command]
            verb = "ran" if self.ran else "run this command"
            return f"{self.client}: {verb}: {shlex.join(shown)}"
        if self.dry_run:
            return f"{self.client}: would write the 'bytnode' server into {self.path}"
        backup = f" (backup: {self.backup})" if self.backup else ""
        return f"{self.client}: 'bytnode' MCP server written into {self.path}{backup}. Restart the client to load it."


def install(
    client: McpClient,
    api_key: str | None = None,
    *,
    path: str | Path | None = None,
    url: str = MCP_URL,
    dry_run: bool = False,
) -> InstallResult:
    """Add (or update) the `bytnode` server in the client's MCP configuration."""
    key = _key(api_key)
    if client == "claude-code":
        cmd = claude_code_command(key, url)
        result = InstallResult(client, command=cmd, dry_run=dry_run)
        if not dry_run and shutil.which("claude"):
            subprocess.run(cmd, check=True)  # noqa: S603 (fixed argv, no shell)
            result.ran = True
        return result
    target = Path(path) if path else config_path(client)
    assert target is not None
    root_key = "servers" if client == "vscode" else "mcpServers"
    current: dict[str, Any] = {}
    if target.exists():
        text = target.read_text(encoding="utf-8").strip()
        if text:
            try:
                current = json.loads(text)
            except ValueError as exc:
                raise ValueError(f"{target} is not valid JSON ({exc}); fix it first, nothing was changed") from None
    servers = current.setdefault(root_key, {})
    if not isinstance(servers, dict):
        raise ValueError(f"{target}: '{root_key}' is not an object; nothing was changed")
    servers[SERVER_NAME] = server_entry(client, key, url)
    result = InstallResult(client, path=target, dry_run=dry_run, content=current)
    if dry_run:
        return result
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        backup = target.with_name(f"{target.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(target, backup)
        result.backup = backup
    target.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def config(client: McpClient, api_key: str | None = None, url: str = MCP_URL) -> dict[str, Any]:
    """The configuration snippet to paste by hand."""
    root_key = "servers" if client == "vscode" else "mcpServers"
    return {root_key: {SERVER_NAME: server_entry(client, _key(api_key), url)}}


__all__ = [
    "CLIENTS",
    "MCP_URL",
    "InstallResult",
    "McpClient",
    "config",
    "config_path",
    "install",
    "mask",
    "server_entry",
]
