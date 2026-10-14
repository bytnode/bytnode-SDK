from __future__ import annotations

import json
from datetime import date, datetime, timezone

import httpx
import pytest
import respx

from bytnode import AsyncBytnode, Bytnode
from bytnode import indicators as ind
from bytnode._indicator_spec import indicators_body
from bytnode._time import to_ms

from .conftest import BASE, SPEC

EXEMPLE = SPEC["paths"]["/v1/klines/history"]["get"]["responses"]["200"]["content"]["application/json"]["example"]
KLINE = EXEMPLE["data"][0]


def page(times: list[str], nxt: dict[str, object] | None) -> dict[str, object]:
    rows = [{**KLINE, "time": t} for t in times]
    enveloppe = {"status": "ok", "server_time": "2026-10-12T09:00:00.000Z", "data_type": "klines_history"}
    return {**enveloppe, "data": rows, "next": nxt}


def test_time_conversions() -> None:
    assert to_ms("2026-01-01") == 1767225600000
    assert to_ms("2026-01-01T00:00:00Z") == 1767225600000
    assert to_ms(date(2026, 1, 1)) == 1767225600000
    assert to_ms(datetime(2026, 1, 1)) == 1767225600000  # naive = UTC
    assert to_ms(datetime(2026, 1, 1, tzinfo=timezone.utc)) == 1767225600000
    assert to_ms(1767225600000) == 1767225600000
    with pytest.raises(ValueError, match="seconds"):
        to_ms(1767225600)
    with pytest.raises(ValueError, match="not a date"):
        to_ms("yesterday")
    with pytest.raises(TypeError):
        to_ms(True)


@respx.mock(base_url=BASE)
def test_query_encoding(respx_mock: respx.MockRouter, client: Bytnode) -> None:
    route = respx_mock.get("/v1/klines/history").mock(return_value=httpx.Response(200, json=page([], None)))
    client.klines.history(
        "BTCUSDT", "1h", since="2026-01-01", before=datetime(2026, 1, 2), fields=["time", "close"], limit=5
    )
    params = route.calls.last.request.url.params
    assert params["since_ms"] == "1767225600000"
    assert params["before_ms"] == "1767312000000"
    assert params["fields"] == "time,close"
    assert params["limit"] == "5"
    assert "until_ms" not in params and "order" not in params  # None is never sent


@respx.mock(base_url=BASE)
def test_fields_give_partial_rows_without_warning(respx_mock: respx.MockRouter, client: Bytnode) -> None:
    body = page([], None)
    body["data"] = [{"time": "2026-10-12T08:00:00.000Z", "close": 1.0}]
    respx_mock.get("/v1/klines/history").mock(return_value=httpx.Response(200, json=body))
    resp = client.klines.history("BTCUSDT", "1h", fields="time,close")
    assert resp.data[0].close == 1.0


@respx.mock(base_url=BASE)
def test_iter_follows_next_and_replaces_the_cursor(respx_mock: respx.MockRouter, client: Bytnode) -> None:
    route = respx_mock.get("/v1/klines/history").mock(
        side_effect=[
            httpx.Response(
                200,
                json=page(
                    ["2026-01-01T00:00:00.000Z", "2026-01-01T01:00:00.000Z"],
                    {"since_ms": 1767232800000, "until_ms": None, "before_ms": None, "order": "asc"},
                ),
            ),
            httpx.Response(200, json=page(["2026-01-01T02:00:00.000Z"], None)),
        ]
    )
    rows = client.klines.history.iter("BTCUSDT", "1h", since="2026-01-01", until="2026-01-02").to_list()
    assert [r.time.hour for r in rows] == [0, 1, 2]
    first, second = (c.request.url.params for c in route.calls)
    assert first["limit"] == "1000"  # the route's maximum: fewest requests
    assert first["order"] == "asc"  # a period read from its start comes oldest first
    assert first["until_ms"] == "1767312000000"
    assert second["since_ms"] == "1767232800000"
    assert "until_ms" not in second  # the cursor of `next` REPLACES ours (null = omitted)


@respx.mock(base_url=BASE)
def test_iter_understands_next_as_a_url(respx_mock: respx.MockRouter, client: Bytnode) -> None:
    route = respx_mock.get("/v1/klines/history").mock(
        side_effect=[
            httpx.Response(
                200,
                json=page(
                    ["2026-01-01T01:00:00.000Z"],
                    "/v1/klines/history?symbol=BTCUSDT&timeframe=1h&limit=1000&before_ms=1767229200000&order=desc",
                ),
            ),
            httpx.Response(200, json=page(["2026-01-01T00:00:00.000Z"], None)),
        ]
    )
    assert len(client.klines.history.iter("BTCUSDT", "1h").to_list()) == 2
    first, second = (c.request.url.params for c in route.calls)
    # Without `since`, no `limit=1000`: the route's default page stops at the plan's
    # history window instead of being refused (403 history_depth) on a small plan.
    assert "limit" not in first
    assert second["before_ms"] == "1767229200000" and second["symbol"] == "BTCUSDT"


@respx.mock(base_url=BASE)
def test_iter_stops_on_empty_page_and_max_items(respx_mock: respx.MockRouter, client: Bytnode) -> None:
    respx_mock.get("/v1/klines/history").mock(
        return_value=httpx.Response(
            200, json=page(["2026-01-01T00:00:00.000Z"] * 3, {"before_ms": 1767225600000, "order": "desc"})
        )
    )
    assert len(client.klines.history.iter("BTCUSDT", "1h", max_items=5).to_list()) == 5


@respx.mock(base_url=BASE)
def test_iter_never_loops_on_a_stuck_cursor(respx_mock: respx.MockRouter, client: Bytnode) -> None:
    stuck = {"before_ms": 1767225600000, "order": "desc"}
    route = respx_mock.get("/v1/klines/history").mock(
        return_value=httpx.Response(200, json=page(["2026-01-01T00:00:00.000Z"], stuck))
    )
    rows = client.klines.history.iter("BTCUSDT", "1h").to_list()
    assert route.call_count == 2 and len(rows) == 2


@respx.mock(base_url=BASE)
def test_iter_trades_enter_range_reading(respx_mock: respx.MockRouter, client: Bytnode) -> None:
    body = {"status": "ok", "server_time": "2026-10-12T09:00:00.000Z", "data": [], "next": None}
    route = respx_mock.get("/v1/trades/spot").mock(return_value=httpx.Response(200, json=body))
    client.trades.spot.iter("BTCUSDT").to_list()
    assert route.calls.last.request.url.params["order"] == "desc"
    assert route.calls.last.request.url.params["limit"] == "10000"


@respx.mock(base_url=BASE)
def test_to_pandas_is_time_indexed_ascending(respx_mock: respx.MockRouter, client: Bytnode) -> None:
    respx_mock.get("/v1/klines/history").mock(
        return_value=httpx.Response(200, json=page(["2026-01-01T02:00:00.000Z", "2026-01-01T01:00:00.000Z"], None))
    )
    df = client.klines.history("BTCUSDT", "1h").to_pandas()
    assert df.index.is_monotonic_increasing and str(df.index.tz) == "UTC"
    assert list(df.columns)[:4] == ["open", "high", "low", "close"]


@respx.mock(base_url=BASE)
async def test_async_iter(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/v1/klines/history").mock(
        side_effect=[
            httpx.Response(200, json=page(["2026-01-01T00:00:00.000Z"], {"before_ms": 1767225600000, "order": "desc"})),
            httpx.Response(200, json=page(["2025-12-31T23:00:00.000Z"], None)),
        ]
    )
    async with AsyncBytnode(api_key="cb_live_k", base_url=BASE) as client:
        rows = [r async for r in client.klines.history.iter("BTCUSDT", "1h")]
        assert len(rows) == 2


@respx.mock(base_url=BASE)
def test_snapshot_query(respx_mock: respx.MockRouter, client: Bytnode) -> None:
    body = {"status": "ok", "server_time": "2026-10-12T09:00:00.000Z", "data": {}}
    route = respx_mock.get("/v1/snapshot").mock(return_value=httpx.Response(200, json=body))
    client.snapshot("BTCUSDT", funding_rate=True, basis=5, klines={"1h": 24, "1w": 2}, cvd={"5m": 3})
    params = dict(route.calls.last.request.url.params)
    assert params == {
        "symbol": "BTCUSDT",
        "funding_rate": "true",
        "basis": "5",
        "klines@1h": "24",
        "klines@1w": "2",
        "cvd@5m": "3",
    }
    with pytest.raises(ValueError, match="at least one field"):
        client.snapshot("BTCUSDT")


@respx.mock(base_url=BASE)
def test_indicators_body(respx_mock: respx.MockRouter, client: Bytnode) -> None:
    body = {"status": "ok", "server_time": "2026-10-12T09:00:00.000Z", "data": None, "unavailable": "not_applicable"}
    route = respx_mock.post("/v1/indicators").mock(return_value=httpx.Response(200, json=body))
    resp = client.indicators("USDCUSDT", "1h", [ind.rsi(14), ind.rsi(14), {"type": "ema", "period": 50}], limit=10)
    import json

    sent = json.loads(route.calls.last.request.content)
    assert sent["limit"] == 10 and sent["symbol"] == "USDCUSDT"
    assert [i["id"] for i in sent["indicators"]] == ["rsi_14", "rsi_14_2", "ema_50"]
    assert resp.data is None and resp.unavailable == "not_applicable"


def test_indicator_checks() -> None:
    with pytest.raises(ValueError, match=r"rsi\.period must be >= 2"):
        ind.rsi(1)
    with pytest.raises(ValueError, match=r"between 0\.5 and 10\.0"):
        ind.bb(20, std=50)
    with pytest.raises(ValueError, match="integer"):
        ind.ema(10.5)  # type: ignore[arg-type]
    assert ind.bb(20, std=2.5).default_id() == "bb_20_2p5"
    assert indicators_body([ind.obv()])[0] == {"id": "obv", "type": "obv"}
    with pytest.raises(ValueError, match="at least one"):
        indicators_body([])


@respx.mock(base_url=BASE)
def test_iter_goes_on_after_a_short_or_empty_page_with_next(respx_mock: respx.MockRouter, client: Bytnode) -> None:
    """An ascending read that reached a dense period returns, within its time budget,
    a short (even empty) page WITH `next`: only `next: null` ends the read."""
    suite = "/v1/klines/history?symbol=BTCUSDT&timeframe=1h&order=asc&limit=1000&since_ms="
    respx_mock.get("/v1/klines/history").mock(
        side_effect=[
            httpx.Response(200, json=page(["2026-01-01T00:00:00.000Z"], suite + "1767312000000")),
            httpx.Response(200, json=page([], suite + "1767398400000")),
            httpx.Response(200, json=page(["2026-01-03T00:00:00.000Z", "2026-01-03T01:00:00.000Z"], None)),
        ]
    )
    rows = client.klines.history.iter("BTCUSDT", "1h", since="2026-01-01").to_list()
    assert len(rows) == 3


@respx.mock(base_url=BASE)
def test_iter_asks_a_smaller_page_after_a_504(respx_mock: respx.MockRouter) -> None:
    client = Bytnode(api_key="cb_live_test_key_0123456789", base_url=BASE, max_retries=0)
    timeout = {
        "status": "error",
        "server_time": "2026-10-13T00:00:00.000Z",
        "error": {"code": "upstream_timeout", "message": "Took too long: reduce the window."},
    }
    ok = page(["2026-01-01T00:00:00.000Z"], None)
    route = respx_mock.get("/v1/klines/history").mock(
        side_effect=[httpx.Response(504, json=timeout), httpx.Response(200, json=ok)]
    )
    rows = client.klines.history.iter("BTCUSDT", "1h", since="2026-01-01").to_list()
    assert len(rows) == 1
    limits = [call.request.url.params["limit"] for call in route.calls]
    assert limits == ["1000", "500"]


@respx.mock(base_url=BASE)
def test_a_successful_response_gives_its_request_id(respx_mock: respx.MockRouter, client: Bytnode) -> None:
    respx_mock.get("/v1/klines/history").mock(
        return_value=httpx.Response(200, json=page([], None), headers={"X-Request-Id": "abc123"})
    )
    assert client.klines.history("BTCUSDT", "1h").request_id == "abc123"


INDICATEURS = {
    "status": "ok",
    "server_time": "2026-10-13T10:00:00.000Z",
    "data_type": "indicators",
    "symbol": "BTCUSDT",
    "timeframe": "1h",
    "data": {
        "indicators": {
            "rsi_14": {
                "type": "rsi",
                "period": 14,
                "values": [
                    {"time": "2026-10-13T09:00:00.000Z", "value": 56.8},
                    {"time": "2026-10-13T08:00:00.000Z", "value": 56.4},
                ],
            },
            "macd_12_26_9": {
                "type": "macd",
                "fast": 12,
                "slow": 26,
                "signal": 9,
                "values": [
                    {"time": "2026-10-13T09:00:00.000Z", "macd": 135.8, "signal": -23.2, "histogram": 159.0},
                    {"time": "2026-10-13T08:00:00.000Z", "macd": 113.2, "signal": -62.9, "histogram": 176.2},
                ],
            },
        }
    },
}


@respx.mock(base_url=BASE)
def test_indicators_rows_newest_first_and_frame(respx_mock: respx.MockRouter, client: Bytnode) -> None:
    route = respx_mock.post("/v1/indicators").mock(return_value=httpx.Response(200, json=INDICATEURS))
    res = client.indicators("BTCUSDT", "1h", [ind.rsi(14), ind.macd()], limit=2)
    assert json.loads(route.calls.last.request.content)["limit"] == 2
    rsi = res.data.indicators["rsi_14"].values
    assert rsi[0].value == 56.8 and rsi[0].time > rsi[1].time  # newest first, typed
    assert res.data.indicators["macd_12_26_9"].values[0].signal == -23.2  # named output (extra attribute)
    df = res.to_pandas()
    assert list(df.columns) == ["rsi_14", "macd_12_26_9.macd", "macd_12_26_9.signal", "macd_12_26_9.histogram"]
    assert df.index.is_monotonic_increasing and df["rsi_14"].iloc[-1] == 56.8
