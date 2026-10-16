"""Every route of the contract: its SDK method builds the right request, and the REAL example
response captured from production parses into its model without a single warning."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from bytnode import Bytnode
from bytnode import indicators as ind
from bytnode._generated.routes import ROUTES

from .conftest import BASE, FORCE_REQUIRED, SAMPLE_VALUES, example, operations

OPS = operations()


def test_every_route_has_a_method() -> None:
    assert len(ROUTES) == len(OPS) == 132
    assert set(ROUTES) == {p for p, _, _ in OPS}


def _method(client: Bytnode, dotted: str) -> Any:
    obj: Any = client
    for part in dotted.split("."):
        obj = getattr(obj, part)
    return obj


def _call(client: Bytnode, path: str, op: dict[str, Any]) -> Any:
    fn = _method(client, ROUTES[path])
    if path == "/v1/snapshot":
        return fn("BTCUSDT", funding_rate=True, basis=2, klines={"1h": 2})
    if path == "/v1/indicators":
        return fn("BTCUSDT", "1h", [ind.rsi(14), ind.macd(), ind.bb(20)], limit=3)
    forced = FORCE_REQUIRED.get(path, [])
    kwargs = {
        p["name"]: SAMPLE_VALUES[p["name"]]
        for p in op.get("parameters", [])
        if p.get("required") or p["name"] in forced
    }
    return fn(**kwargs)


@pytest.mark.parametrize(("path", "method", "op"), OPS, ids=[p for p, _, _ in OPS])
def test_route_parses_its_real_example(client: Bytnode, path: str, method: str, op: dict[str, Any]) -> None:
    expected_path = path.replace("{symbol}", "BTCUSDT")
    with respx.mock(base_url=BASE, assert_all_called=True) as mock:
        route = mock.route(method=method.upper(), path=expected_path).mock(
            return_value=httpx.Response(200, json=example(op))
        )
        resp = _call(client, path, op)
    sent = route.calls.last.request
    assert sent.headers["X-API-KEY"] == "cb_live_test_key_0123456789"
    assert sent.headers["User-Agent"].startswith("bytnode-python/")
    for p in op.get("parameters", []):
        if p.get("required") and p["in"] == "query":
            assert sent.url.params.get(p["name"]) == str(SAMPLE_VALUES[p["name"]])
    data = example(op).get("data")
    if isinstance(data, list):
        assert len(resp) == len(data)
    assert resp.server_time is not None
    # the parsed rows round-trip to the very keys of the API
    for row, raw in zip(resp, data if isinstance(data, list) else [data] if data else [], strict=False):
        if hasattr(row, "to_dict") and isinstance(raw, dict):
            assert set(raw) <= set(row.to_dict())
