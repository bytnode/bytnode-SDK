"""The WebSocket client against a local server that speaks the BytNode stream protocol."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from http import HTTPStatus
from typing import Any

import pytest
from websockets.sync.server import Request, ServerConnection, serve

from bytnode import (
    AsyncBytnode,
    AuthenticationError,
    BookMessage,
    Bytnode,
    ConnectionLimitError,
    StreamError,
    TradesMessage,
)
from bytnode import channels as ch

T = "2026-10-12T09:00:00.000Z"


def trades(seq: int, channel: str = "trades.futures.BTCUSDT") -> str:
    row = {"time": T, "id": f"id{seq}", "side": "buy", "price": 83000.0, "quantity": 0.01, "value_usd": 830.0}
    return json.dumps({"channel": channel, "server_time": T, "seq": seq, "data": [row]})


def book(seq: int) -> str:
    data = {
        "bids": [[82999.0, 1.5]],
        "asks": [[83001.0, 2.0]],
        "mid_avg": 83000.0,
        "avg_spread_bps": 0.03,
        "is_crossed": False,
        "crossed_bps": 0.0,
    }
    return json.dumps({"channel": "book.futures.BTCUSDT", "server_time": T, "seq": seq, "data": data})


class FakeStream:
    """Each connection runs the next script of `scripts` after answering the subscription."""

    def __init__(self, scripts: list[Callable[[ServerConnection], None]]) -> None:
        self.scripts = scripts
        self.connections = 0
        self.frames: list[dict[str, Any]] = []
        self.keys: list[str | None] = []

    def process_request(self, conn: ServerConnection, request: Request) -> Any:
        key = request.headers.get("X-API-KEY")
        self.keys.append(key)
        if key == "bad":
            body = json.dumps(
                {
                    "status": "error",
                    "server_time": T,
                    "error": {"code": "invalid_api_key", "message": "API key missing, invalid or revoked."},
                }
            )
            resp = conn.respond(HTTPStatus.UNAUTHORIZED, body)
            resp.headers["X-Deny-Reason"] = "key"
            resp.headers["Content-Type"] = "application/json"
            return resp
        return None

    def handler(self, conn: ServerConnection) -> None:
        script = self.scripts[min(self.connections, len(self.scripts) - 1)]
        self.connections += 1
        active: set[str] = set()
        for raw in conn:
            frame = json.loads(raw)
            self.frames.append(frame)
            if frame["op"] == "subscribe":
                bad = [c for c in frame["channels"] if c.endswith("FAKE")]
                if bad:
                    conn.send(
                        json.dumps({"op": "error", "code": "invalid_symbol", "message": f"Unknown symbol in {bad[0]}"})
                    )
                    continue
                active |= set(frame["channels"])
                conn.send(json.dumps({"op": "subscribed", "channels": sorted(active)}))
                script(conn)
                return


@pytest.fixture
def server() -> Iterator[Callable[[list[Callable[[ServerConnection], None]]], tuple[str, FakeStream]]]:
    started: list[Any] = []

    def start(scripts: list[Callable[[ServerConnection], None]]) -> tuple[str, FakeStream]:
        fake = FakeStream(scripts)
        srv = serve(fake.handler, "127.0.0.1", 0, process_request=fake.process_request)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        started.append(srv)
        return f"ws://127.0.0.1:{srv.socket.getsockname()[1]}/ws", fake

    yield start
    for srv in started:
        srv.shutdown()


@pytest.fixture(autouse=True)
def _fast_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bytnode._stream._backoff", lambda _attempt: 0.01)


def _sync(url: str, key: str = "cb_live_k") -> Bytnode:
    return Bytnode(api_key=key, stream_url=url, base_url="https://api.test.bytnode")


def test_channel_helpers() -> None:
    assert ch.trades("btcusdt") == "trades.futures.BTCUSDT"
    assert ch.book("ETHUSDT", market="spot") == "book.spot.ETHUSDT"
    assert ch.liquidations("solusdt") == "liquidations.SOLUSDT"
    with pytest.raises(ValueError):
        ch.trades("BTCUSDT", market="perp")  # type: ignore[arg-type]


def test_sync_stream_typed_messages_and_gaps(server: Any) -> None:
    def script(conn: ServerConnection) -> None:
        for frame in (trades(10), trades(11), book(500), trades(14)):
            conn.send(frame)
        conn.close(1000)

    url, fake = server([script])
    with _sync(url).stream("trades.futures.btcusdt", ch.book("BTCUSDT"), depth=3, reconnect=False) as s:
        assert s.channels == ["book.futures.BTCUSDT", "trades.futures.BTCUSDT"]
        msgs = []
        with pytest.raises(StreamError, match="closed"):
            for m in s:
                msgs.append(m)
    assert fake.keys == ["cb_live_k"]  # the key travels in a header, never in the URL
    assert fake.frames[0] == {
        "op": "subscribe",
        "channels": ["book.futures.BTCUSDT", "trades.futures.BTCUSDT"],
        "depth": 3,
    }
    assert [type(m) for m in msgs] == [TradesMessage, TradesMessage, BookMessage, TradesMessage]
    assert [m.gap for m in msgs] == [0, 0, 0, 2]  # 12 and 13 were lost
    first = msgs[0]
    assert isinstance(first, TradesMessage)
    assert (
        first.data[0].price == 83000.0
        and first.kind == "trades"
        and first.market == "futures"
        and first.symbol == "BTCUSDT"
    )
    b = msgs[2]
    assert isinstance(b, BookMessage) and b.data.bids[0] == (82999.0, 1.5)


def test_sync_stream_reconnects_and_resubscribes(server: Any) -> None:
    def drop(conn: ServerConnection) -> None:
        conn.send(trades(1))
        conn.close(1011, "restart")

    def then(conn: ServerConnection) -> None:
        conn.send(trades(5))
        conn.close(4003, "connection ceiling reached (3)")

    url, fake = server([drop, then])
    with _sync(url).stream(ch.trades("BTCUSDT")) as s:
        got = []
        with pytest.raises(ConnectionLimitError):
            for m in s:
                got.append(m)
        assert s.reconnects == 1
    assert [m.seq for m in got] == [1, 5] and got[1].gap == 3
    assert fake.connections == 2 and [f["op"] for f in fake.frames] == ["subscribe", "subscribe"]


def test_handshake_refusal_is_an_authentication_error(server: Any) -> None:
    url, _ = server([lambda conn: None])
    with pytest.raises(AuthenticationError) as exc, _sync(url, key="bad").stream(ch.trades("BTCUSDT")):
        pass
    assert exc.value.code == "invalid_api_key" and exc.value.reason == "key"


def test_subscribe_error_is_raised(server: Any) -> None:
    url, _ = server([lambda conn: conn.close(1000)])
    with pytest.raises(StreamError, match="Unknown symbol"), _sync(url).stream("trades.futures.FAKE"):
        pass


async def test_async_stream(server: Any) -> None:
    def script(conn: ServerConnection) -> None:
        conn.send(trades(1))
        conn.send(trades(3))
        conn.close(1011)

    def second(conn: ServerConnection) -> None:
        conn.send(trades(4))
        conn.close(4001, "invalid key")

    url, fake = server([script, second])
    client = AsyncBytnode(api_key="cb_live_k", stream_url=url, base_url="https://x")
    async with client, client.stream(ch.trades("BTCUSDT")) as s:
        got = []
        with pytest.raises(StreamError) as exc:
            async for m in s:
                got.append(m)
        assert exc.value.close_code == 4001
        assert s.reconnects == 1
    assert [m.seq for m in got] == [1, 3, 4] and [m.gap for m in got] == [0, 1, 0]
    assert fake.connections == 2


def test_depth_is_checked() -> None:
    with pytest.raises(ValueError, match="between 1 and 5"):
        _sync("ws://127.0.0.1:1/ws").stream(ch.book("BTCUSDT"), depth=9)
