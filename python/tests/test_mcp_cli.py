from __future__ import annotations

import json
from pathlib import Path

import pytest

from bytnode import mcp
from bytnode.cli import main

KEY = "cb_live_abcdefghijklmnop1234"


def test_install_merges_and_backs_up(tmp_path: Path) -> None:
    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {"other": {"url": "https://x"}}, "keep": 1}), encoding="utf-8")
    result = mcp.install("cursor", KEY, path=cfg)
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["keep"] == 1 and "other" in data["mcpServers"]
    assert data["mcpServers"]["bytnode"] == {"url": mcp.MCP_URL, "headers": {"X-API-KEY": KEY}}
    assert result.backup is not None and result.backup.exists()


def test_install_creates_the_file(tmp_path: Path) -> None:
    cfg = tmp_path / "sub" / "mcp.json"
    mcp.install("vscode", KEY, path=cfg)
    assert json.loads(cfg.read_text(encoding="utf-8"))["servers"]["bytnode"]["type"] == "http"


def test_install_refuses_broken_json(tmp_path: Path) -> None:
    cfg = tmp_path / "mcp.json"
    cfg.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        mcp.install("cursor", KEY, path=cfg)
    assert cfg.read_text(encoding="utf-8") == "{not json"


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    cfg = tmp_path / "mcp.json"
    mcp.install("windsurf", KEY, path=cfg, dry_run=True)
    assert not cfg.exists()


def test_claude_desktop_uses_mcp_remote() -> None:
    entry = mcp.server_entry("claude-desktop", KEY)
    assert entry["command"] == "npx" and "mcp-remote" in entry["args"]
    assert entry["env"]["BYTNODE_API_KEY"] == KEY


def test_claude_code_command() -> None:
    cmd = mcp.claude_code_command(KEY)
    assert cmd[:5] == ["claude", "mcp", "add", "--transport", "http"] and f"X-API-KEY: {KEY}" in cmd
    assert KEY not in mcp.InstallResult("claude-code", command=cmd).describe()


def test_cli_config_masks_the_key(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYTNODE_API_KEY", KEY)
    assert main(["mcp", "config", "cursor"]) == 0
    out = capsys.readouterr().out
    assert KEY not in out and "cb_live_abcd..." in out


def test_cli_without_key(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BYTNODE_API_KEY", raising=False)
    assert main(["mcp", "config", "cursor"]) == 1
    assert "BYTNODE_API_KEY" in capsys.readouterr().err
