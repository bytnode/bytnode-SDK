"""Against the PRODUCTION API, read-only: `BYTNODE_API_KEY=... pytest -m live`.

Deselected by default. A handful of spaced requests: latest values, a paginated history,
an error, a snapshot, indicators and ten seconds of WebSocket stream.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator

import pytest

from bytnode import AsyncBytnode, Bytnode, InvalidRequestError, TradesMessage
from bytnode import channels as ch
from bytnode import indicators as ind

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("BYTNODE_API_KEY"), reason="BYTNODE_API_KEY is not set"),
]


@pytest.fixture(autouse=True)
def _real_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()  # the conftest no-sleep patch must not apply to the real API


@pytest.fixture
def live() -> Iterator[Bytnode]:
    with Bytnode() as client:
        yield client
    time.sleep(0.5)  # be gentle with the API between tests


def test_latest_values(live: Bytnode) -> None:
    candles = live.klines("BTCUSDT", "1h", limit=3)
    assert len(candles) == 3 and candles.data[0].close > 0 and candles.symbol == "BTCUSDT"
    funding = live.funding.rate("BTCUSDT")
    assert funding.data is not None and funding.data.time is not None
    assert live.btc.fees().data is not None
    assert len(live.symbols()) >= 20


def test_paginated_history(live: Bytnode) -> None:
    rows = live.klines.iter("BTCUSDT", "1h", since="2026-10-01", until="2026-10-03", page_size=10).to_list()
    hours = [r.time for r in rows]
    assert len(rows) == 49 and hours == sorted(hours) and len(set(hours)) == len(hours)


def test_pandas(live: Bytnode) -> None:
    df = live.funding.rate.history.iter("BTCUSDT", since="2026-09-01", max_items=30).to_pandas()
    assert len(df) == 30 and df.index.is_monotonic_increasing and "rate_pct" in df.columns


def test_error_is_typed(live: Bytnode) -> None:
    with pytest.raises(InvalidRequestError) as exc:
        live.klines("NOPEUSDT", "1h")
    assert exc.value.code == "invalid_symbol" and exc.value.param == "symbol"


def test_snapshot_and_indicators(live: Bytnode) -> None:
    snap = live.snapshot("ETHUSDT", funding_rate=True, klines={"1h": 3})
    assert snap.data.funding_rate is not None and len(snap.data.klines_1h or []) == 3
    res = live.indicators("BTCUSDT", "1h", [ind.rsi(14), ind.macd(), ind.bb(20)], results=5)
    assert res.data is not None and set(res.data.indicators) == {"rsi_14", "macd_12_26_9", "bb_20_2"}
    df = res.to_pandas()
    assert len(df) == 5 and "macd_12_26_9.signal" in df.columns


def test_stream_sync(live: Bytnode) -> None:
    seen: list[str] = []
    deadline = time.monotonic() + 10
    with live.stream(ch.trades("BTCUSDT"), ch.book("BTCUSDT"), depth=3) as stream:
        for msg in stream:
            seen.append(msg.kind)
            if isinstance(msg, TradesMessage):
                assert msg.data[0].price > 0
            if time.monotonic() > deadline or ({"trades", "book"} <= set(seen) and len(seen) > 5):
                break
    assert {"trades", "book"} <= set(seen)


async def test_async_client_and_stream() -> None:
    async with AsyncBytnode() as client:
        candles = await client.klines("SOLUSDT", "5m", limit=2)
        assert len(candles) == 2
        async with client.stream(ch.trades("ETHUSDT")) as stream:
            async for msg in stream:
                assert msg.channel == "trades.futures.ETHUSDT"
                break
