"""The real-time WebSocket stream: subscriptions, typed messages, automatic reconnection.

The protocol (https://bytnode.com/docs/websocket): the key is checked at the handshake;
`{"op": "subscribe", "channels": [...], "depth": N}` answers `op: subscribed` with EVERY active
channel; data messages carry `channel`, `server_time`, `seq` (monotonic per channel, arbitrary start)
and `data`. A jump in `seq` on an event channel means messages were lost.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections import deque
from collections.abc import AsyncIterator, Iterable, Iterator
from datetime import datetime
from typing import Any, Union

from pydantic import Field as PydField

from ._errors import APIError, BytnodeError, ConnectionLimitError, StreamError, error_from_response
from ._models_base import BytnodeModel
from ._version import __version__

USER_AGENT = f"bytnode-python/{__version__}"
REPLY_TIMEOUT_S = 10.0
_EVENT_KINDS = {"trades", "liquidations"}


# --------------------------------------------------------------------------- messages


class StreamTrade(BytnodeModel):
    """One execution. `side` is the taker's side (`buy` = a buyer lifted the offer)."""

    time: datetime = PydField(description="Instant of the trade.")
    id: str | None = PydField(None, description="Same id as /v1/trades/*: deduplicate against REST.")
    side: str = PydField(description="Taker side: `buy` or `sell`.")
    price: float
    quantity: float = PydField(description="In units of the base asset.")
    value_usd: float | None = PydField(None, description="price × quantity, in USD.")


class StreamLiquidation(BytnodeModel):
    """One liquidation. `side` is the side of the liquidated position (`long` = a long was liquidated)."""

    time: datetime
    price: float
    quantity: float
    side: str = PydField(description="`long` or `short`: the liquidated position.")
    value_usd: float | None = None


class StreamBook(BytnodeModel):
    """The consolidated order book: `[price, quantity]` levels re-centred on `mid_avg`."""

    bids: list[tuple[float, float]] = PydField(default_factory=list, description="Decreasing prices.")
    asks: list[tuple[float, float]] = PydField(default_factory=list, description="Increasing prices.")
    mid_avg: float | None = PydField(None, description="Reference price.")
    avg_spread_bps: float | None = PydField(None, description="Average per-venue spread, in basis points.")
    is_crossed: bool | None = None
    crossed_bps: float | None = None


class StreamMessage(BytnodeModel):
    """A message of the stream. `gap` counts the messages LOST just before this one."""

    channel: str
    server_time: datetime = PydField(description="When the server sent the message.")
    seq: int | None = None
    gap: int = PydField(0, description="Messages lost before this one on its channel (event channels only).")

    @property
    def kind(self) -> str:
        """`trades`, `liquidations` or `book`."""
        return self.channel.split(".", 1)[0]

    @property
    def market(self) -> str | None:
        """`futures` or `spot` (`None` for liquidations, futures only)."""
        parts = self.channel.split(".")
        return parts[1] if len(parts) == 3 else None

    @property
    def symbol(self) -> str:
        return self.channel.rsplit(".", 1)[-1]


class TradesMessage(StreamMessage):
    data: list[StreamTrade] = PydField(default_factory=list)


class LiquidationsMessage(StreamMessage):
    data: list[StreamLiquidation] = PydField(default_factory=list)


class BookMessage(StreamMessage):
    data: StreamBook


AnyMessage = Union[TradesMessage, LiquidationsMessage, BookMessage]


def parse_message(obj: dict[str, Any]) -> AnyMessage:
    kind = str(obj.get("channel", "")).split(".", 1)[0]
    if kind == "book":
        return BookMessage.model_validate(obj)
    if kind == "liquidations":
        return LiquidationsMessage.model_validate(obj)
    return TradesMessage.model_validate(obj)


def normalize_channel(channel: str) -> str:
    """`trades.futures.btcusdt` -> `trades.futures.BTCUSDT` (the API is case-insensitive)."""
    parts = channel.strip().split(".")
    if len(parts) < 2:
        raise ValueError(f"invalid channel {channel!r}: expected e.g. 'trades.futures.BTCUSDT' (see bytnode.channels)")
    return ".".join([*(p.lower() for p in parts[:-1]), parts[-1].upper()])


# --------------------------------------------------------------------------- reconnection


def _backoff(attempt: int) -> float:
    return min(30.0, 0.5 * 2.0**attempt) * (0.5 + random.random() / 2)  # noqa: S311


def classify_close(code: int | None, reason: str) -> BytnodeError | None:
    """The error to raise for a closing code, or `None` when reconnecting is the right move."""
    if code == 4001:
        return StreamError(reason or "key refused", code="invalid_api_key", close_code=code)
    if code == 4003:
        if "slow" in reason.lower():
            return None  # the client fell behind: reconnect, it starts fresh
        return ConnectionLimitError(
            reason or "the plan's ceiling of simultaneous connections is reached",
            code="connection_limit",
            close_code=code,
        )
    if code == 1008:
        return StreamError(reason or "policy violation", code="policy_violation", close_code=code)
    return None


def classify_handshake(status: int, headers: Any, body: bytes | bytearray) -> tuple[APIError, bool]:
    """The error of a refused handshake, and whether retrying can help (429, 5xx)."""
    err = error_from_response(status, headers, bytes(body))
    return err, status == 429 or status >= 500


class _Tracker:
    """Shared by both streams: active channels, depth, gap detection."""

    def __init__(self, channels: Iterable[str], depth: int | None) -> None:
        self.wanted: set[str] = {normalize_channel(c) for c in channels}
        self.depth = depth
        self.active: list[str] = []
        self._expected: dict[str, int] = {}

    def frame(self, op: str, channels: Iterable[str]) -> str:
        msg: dict[str, Any] = {"op": op, "channels": sorted(channels)}
        if op == "subscribe" and self.depth is not None:
            msg["depth"] = self.depth
        return json.dumps(msg)

    def gap(self, msg: StreamMessage) -> None:
        if msg.seq is None or msg.kind not in _EVENT_KINDS:
            return
        expected = self._expected.get(msg.channel)
        if expected is not None and msg.seq > expected:
            msg.gap = msg.seq - expected
        self._expected[msg.channel] = msg.seq + 1


def _check_depth(depth: int | None) -> None:
    if depth is not None and not 1 <= depth <= 5:
        raise ValueError(f"depth must be between 1 and 5, got {depth}")


# --------------------------------------------------------------------------- async


_END = object()


class AsyncStream:
    """`async with client.stream("trades.futures.BTCUSDT") as s: async for msg in s: ...`

    Attributes:
        channels: the active channels, as last confirmed by the server.
        reconnects: how many times the stream reconnected.
    """

    def __init__(
        self,
        url: str,
        api_key: str,
        channels: list[str],
        *,
        depth: int | None = None,
        reconnect: bool = True,
        max_reconnects: int | None = None,
        open_timeout: float = 10.0,
        queue_size: int = 10_000,
    ) -> None:
        _check_depth(depth)
        self._url = url
        self._key = api_key
        self._tracker = _Tracker(channels, depth)
        self._reconnect = reconnect
        self._max_reconnects = max_reconnects
        self._open_timeout = open_timeout
        self._queue_size = queue_size
        self._ws: Any = None
        self._reader: asyncio.Task[None] | None = None
        self._queue: asyncio.Queue[Any] | None = None
        self._pending: deque[asyncio.Future[dict[str, Any]]] = deque()
        self._closed = False
        self.reconnects = 0
        self.dropped = 0  # messages dropped locally because the consumer was too slow

    @property
    def channels(self) -> list[str]:
        return list(self._tracker.active)

    async def __aenter__(self) -> AsyncStream:
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def connect(self) -> None:
        """Open the connection and subscribe to the channels given at creation."""
        self._queue = asyncio.Queue(self._queue_size)
        await self._open()
        self._reader = asyncio.create_task(self._run())
        if self._tracker.wanted:
            await self._ask("subscribe", self._tracker.wanted)

    async def _open(self) -> None:
        from websockets.asyncio.client import connect
        from websockets.exceptions import InvalidStatus

        try:
            self._ws = await connect(
                self._url,
                additional_headers={"X-API-KEY": self._key},
                user_agent_header=USER_AGENT,
                open_timeout=self._open_timeout,
                max_size=None,
            )
        except InvalidStatus as exc:
            err, _ = classify_handshake(exc.response.status_code, exc.response.headers, exc.response.body or b"")
            raise err from None

    async def subscribe(self, *channels: str, depth: int | None = None) -> list[str]:
        """Add channels; returns every active channel. All or nothing: one bad channel, none applied."""
        if depth is not None:
            _check_depth(depth)
            self._tracker.depth = depth
        names = {normalize_channel(c) for c in channels}
        reply = await self._ask("subscribe", names)
        self._tracker.wanted |= names
        return list(reply.get("channels") or [])

    async def unsubscribe(self, *channels: str) -> list[str]:
        """Remove channels; returns the channels still active."""
        names = {normalize_channel(c) for c in channels}
        reply = await self._ask("unsubscribe", names)
        self._tracker.wanted -= names
        return list(reply.get("channels") or [])

    async def _ask(self, op: str, channels: Iterable[str]) -> dict[str, Any]:
        if self._ws is None:
            raise StreamError(
                "the stream is not connected: use `async with client.stream(...)` or `await stream.connect()`"
            )
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending.append(fut)
        await self._ws.send(self._tracker.frame(op, channels))
        return await asyncio.wait_for(fut, REPLY_TIMEOUT_S)

    def _handle(self, raw: str | bytes) -> None:
        obj = json.loads(raw)
        op = obj.get("op")
        if op is not None:
            if op == "error":
                err = StreamError(obj.get("message") or "stream error", code=obj.get("code"))
                if self._pending:
                    self._pending.popleft().set_exception(err)
                else:
                    self._put(err)
                return
            if "channels" in obj:
                self._tracker.active = list(obj["channels"])
            if self._pending and op in ("subscribed", "unsubscribed"):
                fut = self._pending.popleft()
                if not fut.done():
                    fut.set_result(obj)
            return
        if "channel" in obj:
            msg = parse_message(obj)
            self._tracker.gap(msg)
            self._put(msg)

    def _put(self, item: Any) -> None:
        assert self._queue is not None
        if self._queue.full():
            self._queue.get_nowait()
            self.dropped += 1
        self._queue.put_nowait(item)

    async def _run(self) -> None:
        from websockets.exceptions import ConnectionClosed, InvalidStatus

        attempt = 0
        while not self._closed:
            opened_at = time.monotonic()
            code, reason = None, ""
            try:
                async for raw in self._ws:
                    self._handle(raw)
                code, reason = self._ws.close_code, self._ws.close_reason or ""
            except ConnectionClosed as exc:
                code = exc.rcvd.code if exc.rcvd else None
                reason = exc.rcvd.reason if exc.rcvd else ""
            except Exception as exc:  # a bug in a message must not kill the stream silently
                self._put(exc)
                return
            if self._closed:
                break
            for fut in self._pending:
                if not fut.done():
                    fut.set_exception(StreamError("connection lost before the server answered", code="connection_lost"))
            self._pending.clear()
            fatal = classify_close(code, reason)
            if fatal or not self._reconnect:
                self._put(
                    fatal or StreamError(f"connection closed ({code} {reason})".strip(), code="closed", close_code=code)
                )
                return
            if time.monotonic() - opened_at > 60:
                attempt = 0
            while not self._closed:
                if self._max_reconnects is not None and self.reconnects >= self._max_reconnects:
                    self._put(StreamError(f"gave up after {self.reconnects} reconnections", code="reconnect_failed"))
                    return
                await asyncio.sleep(_backoff(attempt))
                attempt += 1
                self.reconnects += 1
                try:
                    await self._open()
                except APIError as exc:
                    if exc.status in (429,) or exc.status >= 500:
                        continue
                    self._put(exc)
                    return
                except (OSError, asyncio.TimeoutError, InvalidStatus):
                    continue
                if self._tracker.wanted:
                    await self._ws.send(self._tracker.frame("subscribe", self._tracker.wanted))
                break
        self._put(_END)

    def __aiter__(self) -> AsyncIterator[AnyMessage]:
        return self

    async def __anext__(self) -> AnyMessage:
        if self._queue is None:
            raise StreamError("the stream is not connected: use `async with client.stream(...)`")
        item = await self._queue.get()
        if item is _END:
            raise StopAsyncIteration
        if isinstance(item, BaseException):
            raise item
        return item  # type: ignore[no-any-return]

    async def close(self) -> None:
        """Close the connection and stop the iteration."""
        self._closed = True
        if self._ws is not None:
            await self._ws.close()
        if self._reader is not None:
            try:
                await asyncio.wait_for(self._reader, 5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._reader.cancel()
        if self._queue is not None and self._queue.empty():
            self._queue.put_nowait(_END)


# --------------------------------------------------------------------------- sync


class SyncStream:
    """`with client.stream("trades.futures.BTCUSDT") as s: for msg in s: ...` (blocking)."""

    def __init__(
        self,
        url: str,
        api_key: str,
        channels: list[str],
        *,
        depth: int | None = None,
        reconnect: bool = True,
        max_reconnects: int | None = None,
        open_timeout: float = 10.0,
    ) -> None:
        _check_depth(depth)
        self._url = url
        self._key = api_key
        self._tracker = _Tracker(channels, depth)
        self._reconnect = reconnect
        self._max_reconnects = max_reconnects
        self._open_timeout = open_timeout
        self._ws: Any = None
        self._buffer: deque[AnyMessage] = deque()
        self._closed = False
        self._opened_at = 0.0
        self.reconnects = 0

    @property
    def channels(self) -> list[str]:
        return list(self._tracker.active)

    def __enter__(self) -> SyncStream:
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def connect(self) -> None:
        self._open()
        if self._tracker.wanted:
            self._ask("subscribe", self._tracker.wanted)

    def _open(self) -> None:
        from websockets.exceptions import InvalidStatus
        from websockets.sync.client import connect

        try:
            self._ws = connect(
                self._url,
                additional_headers={"X-API-KEY": self._key},
                user_agent_header=USER_AGENT,
                open_timeout=self._open_timeout,
                max_size=None,
            )
        except InvalidStatus as exc:
            err, _ = classify_handshake(exc.response.status_code, exc.response.headers, exc.response.body or b"")
            raise err from None
        self._opened_at = time.monotonic()

    def subscribe(self, *channels: str, depth: int | None = None) -> list[str]:
        """Add channels; returns every active channel."""
        if depth is not None:
            _check_depth(depth)
            self._tracker.depth = depth
        names = {normalize_channel(c) for c in channels}
        reply = self._ask("subscribe", names)
        self._tracker.wanted |= names
        return list(reply.get("channels") or [])

    def unsubscribe(self, *channels: str) -> list[str]:
        names = {normalize_channel(c) for c in channels}
        reply = self._ask("unsubscribe", names)
        self._tracker.wanted -= names
        return list(reply.get("channels") or [])

    def _ask(self, op: str, channels: Iterable[str]) -> dict[str, Any]:
        if self._ws is None:
            raise StreamError("the stream is not connected: use `with client.stream(...)` or `stream.connect()`")
        self._ws.send(self._tracker.frame(op, channels))
        deadline = time.monotonic() + REPLY_TIMEOUT_S
        while True:
            raw = self._ws.recv(timeout=max(0.1, deadline - time.monotonic()))
            obj = json.loads(raw)
            reply = obj.get("op")
            if reply == "error":
                raise StreamError(obj.get("message") or "stream error", code=obj.get("code"))
            if reply in ("subscribed", "unsubscribed"):
                self._tracker.active = list(obj.get("channels") or [])
                return obj  # type: ignore[no-any-return]
            if "channel" in obj:
                msg = parse_message(obj)
                self._tracker.gap(msg)
                self._buffer.append(msg)

    def __iter__(self) -> Iterator[AnyMessage]:
        return self

    def __next__(self) -> AnyMessage:
        from websockets.exceptions import ConnectionClosed

        if self._buffer:
            return self._buffer.popleft()
        attempt = 0
        while not self._closed:
            if self._ws is None:
                raise StreamError("the stream is not connected: use `with client.stream(...)`")
            try:
                obj = json.loads(self._ws.recv())
            except ConnectionClosed as exc:
                if self._closed:
                    break
                code = exc.rcvd.code if exc.rcvd else None
                reason = exc.rcvd.reason if exc.rcvd else ""
                fatal = classify_close(code, reason)
                if fatal:
                    raise fatal from None
                if not self._reconnect:
                    raise StreamError(
                        f"connection closed ({code} {reason})".strip(), code="closed", close_code=code
                    ) from None
                if time.monotonic() - self._opened_at > 60:
                    attempt = 0
                attempt = self._reopen(attempt)
                continue
            op = obj.get("op")
            if op == "error":
                raise StreamError(obj.get("message") or "stream error", code=obj.get("code"))
            if op is not None:
                if "channels" in obj:
                    self._tracker.active = list(obj["channels"])
                continue
            if "channel" in obj:
                msg = parse_message(obj)
                self._tracker.gap(msg)
                return msg
        raise StopIteration

    def _reopen(self, attempt: int) -> int:
        while True:
            if self._max_reconnects is not None and self.reconnects >= self._max_reconnects:
                raise StreamError(f"gave up after {self.reconnects} reconnections", code="reconnect_failed")
            time.sleep(_backoff(attempt))
            attempt += 1
            self.reconnects += 1
            try:
                self._open()
            except APIError as exc:
                if exc.status == 429 or exc.status >= 500:
                    continue
                raise
            except (OSError, TimeoutError):
                continue
            if self._tracker.wanted:
                self._ws.send(self._tracker.frame("subscribe", self._tracker.wanted))
            return attempt

    def close(self) -> None:
        self._closed = True
        if self._ws is not None:
            self._ws.close()


__all__ = [
    "AnyMessage",
    "AsyncStream",
    "BookMessage",
    "LiquidationsMessage",
    "StreamBook",
    "StreamLiquidation",
    "StreamMessage",
    "StreamTrade",
    "SyncStream",
    "TradesMessage",
]
