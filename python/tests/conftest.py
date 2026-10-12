from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from bytnode import Bytnode

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "spec" / "openapi.json").read_text(encoding="utf-8"))
FORCE_REQUIRED: dict[str, list[str]] = json.loads((ROOT / "codegen" / "overrides.json").read_text(encoding="utf-8"))[
    "force_required"
]
BASE = "https://api.test.bytnode"

# A valid value for every required parameter of the contract.
SAMPLE_VALUES: dict[str, Any] = {
    "symbol": "BTCUSDT",
    "timeframe": "1h",
    "asset": "BTC",
    "series": "DGS10",
    "expiry": "2026-10-30",
    "dataset": "concentration",
}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retries back off for real in production; in tests they must not wait."""
    monkeypatch.setattr("bytnode._transport.time.sleep", lambda _s: None)

    async def _instant(_s: float) -> None:
        return None

    monkeypatch.setattr("bytnode._transport.asyncio.sleep", _instant)
    monkeypatch.delenv("BYTNODE_BASE_URL", raising=False)


@pytest.fixture
def client() -> Bytnode:
    return Bytnode(api_key="cb_live_test_key_0123456789", base_url=BASE)


def operations() -> list[tuple[str, str, dict[str, Any]]]:
    out = []
    for path, ops in SPEC["paths"].items():
        for method, op in ops.items():
            if method in ("get", "post"):
                out.append((path, method, op))
    return out


def example(op: dict[str, Any]) -> dict[str, Any]:
    return op["responses"]["200"]["content"]["application/json"]["example"]  # type: ignore[no-any-return]
