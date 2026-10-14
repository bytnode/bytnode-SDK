"""The two clients: `Bytnode` (synchronous) and `AsyncBytnode` (asyncio)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from types import TracebackType
from typing import TYPE_CHECKING, Any

from ._errors import MissingAPIKeyError
from ._generated.async_resources import AsyncResources
from ._generated.indicators_result import IndicatorsResult
from ._generated.resources import Resources
from ._generated.snapshot import SnapshotData
from ._ratelimit import RateLimit
from ._response import Response, parse_row
from ._routes import RouteSpec
from ._stream import AsyncStream, SyncStream
from ._transport import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    AsyncTransport,
    SyncTransport,
    build_request,
)
from ._types import RequestOptions

if TYPE_CHECKING:
    import httpx

DEFAULT_STREAM_URL = "wss://api.bytnode.com/ws"


def _resolve_key(api_key: str | None) -> str:
    key = api_key or os.environ.get("BYTNODE_API_KEY")
    if not key:
        raise MissingAPIKeyError()
    return key.strip()


def _parse(route: RouteSpec, raw: dict[str, Any], partial: bool) -> Any:
    data = raw.get("data")
    if route.shape == "list":
        rows = data if isinstance(data, list) else ([] if data is None else [data])
        return [parse_row(route.model, r, partial=partial) for r in rows]
    if route.shape == "object":
        if isinstance(data, list):  # defensive: a latest route always serves an object
            return [parse_row(route.model, r, partial=partial) for r in data]
        return None if data is None else parse_row(route.model, data, partial=partial)
    if route.shape == "snapshot":
        return parse_row(SnapshotData, data or {}, partial=partial)
    if route.shape == "indicators":
        return None if data is None else parse_row(IndicatorsResult, data)
    return data


class _Common:
    _last_rate_limit: RateLimit | None

    @property
    def last_rate_limit(self) -> RateLimit | None:
        """Your rate limit and monthly quota, as announced by the last response."""
        return self._last_rate_limit

    def _response(self, route: RouteSpec, http: httpx.Response, raw: dict[str, Any], partial: bool) -> Response[Any]:
        resp: Response[Any] = Response(
            _parse(route, raw, partial), raw=raw, route=route, status_code=http.status_code, headers=http.headers
        )
        if resp.rate_limit is not None:
            self._last_rate_limit = resp.rate_limit
        return resp


class Bytnode(Resources, _Common):
    """Synchronous client of the BytNode API.

        from bytnode import Bytnode

        client = Bytnode()                      # reads BYTNODE_API_KEY
        candles = client.klines.history("BTCUSDT", "1h", limit=24)
        print(candles.data[0].close)
        df = client.klines.history.iter("BTCUSDT", "1h", since="2026-01-01").to_pandas()

    Every route is an attribute named after its path: `/v1/funding/rate/history` is
    `client.funding.rate.history(...)`. Use it as a context manager, or call `close()`.

    Args:
        api_key: your key (`cb_live_...`). Default: the `BYTNODE_API_KEY` environment variable.
        base_url: default `https://api.bytnode.com` (or `BYTNODE_BASE_URL`).
        timeout: seconds per attempt (default 30).
        max_retries: automatic retries on 429 (rate limit), 502, 503, 504 and network errors
            (default 3; a spent monthly quota is never retried).
        default_headers: extra headers sent with every request.
        http_client: your own `httpx.Client` (proxies, custom TLS...).
        stream_url: WebSocket URL (default `wss://api.bytnode.com/ws`).
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        default_headers: Mapping[str, str] | None = None,
        http_client: httpx.Client | None = None,
        stream_url: str | None = None,
    ) -> None:
        self.api_key = _resolve_key(api_key)
        self.base_url = base_url or os.environ.get("BYTNODE_BASE_URL") or DEFAULT_BASE_URL
        self.stream_url = stream_url or os.environ.get("BYTNODE_STREAM_URL") or DEFAULT_STREAM_URL
        self._transport = SyncTransport(
            self.api_key, self.base_url, timeout, max_retries, default_headers, http_client=http_client
        )
        self._last_rate_limit = None
        self._init_resources()

    def _request(
        self, route: RouteSpec, params: Mapping[str, Any], options: RequestOptions | None, *, body: Any = None
    ) -> Response[Any]:
        path, query = build_request(route, params)
        http, raw = self._transport.request(route.method, path, query=query, body=body, options=options)
        return self._response(route, http, raw, partial=query.get("fields") is not None)

    def stream(
        self,
        *channels: str,
        depth: int | None = None,
        reconnect: bool = True,
        max_reconnects: int | None = None,
        open_timeout: float = 10.0,
    ) -> SyncStream:
        """The real-time WebSocket stream (blocking iterator).

            with client.stream("trades.futures.BTCUSDT", "orderbook.futures.BTCUSDT") as stream:
                for msg in stream:
                    print(msg.channel, msg.data)

        Reconnects by itself and subscribes again; `msg.gap` counts the messages lost before
        `msg` on an event channel. See `bytnode.channels` to build channel names.
        """
        return SyncStream(
            self.stream_url,
            self.api_key,
            list(channels),
            depth=depth,
            reconnect=reconnect,
            max_reconnects=max_reconnects,
            open_timeout=open_timeout,
        )

    def close(self) -> None:
        """Release the HTTP connections."""
        self._transport.close()

    def __enter__(self) -> Bytnode:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"<Bytnode base_url={self.base_url!r}>"


class AsyncBytnode(AsyncResources, _Common):
    """Asynchronous client of the BytNode API (asyncio).

        from bytnode import AsyncBytnode

        async with AsyncBytnode() as client:
            candles = await client.klines.history("BTCUSDT", "1h", limit=24)
            async for row in client.funding.rate.history.iter("BTCUSDT", since="2026-01-01"):
                ...
            async with client.stream("trades.futures.BTCUSDT") as stream:
                async for msg in stream:
                    ...

    Same arguments as `Bytnode`; `http_client` is an `httpx.AsyncClient`.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        default_headers: Mapping[str, str] | None = None,
        http_client: httpx.AsyncClient | None = None,
        stream_url: str | None = None,
    ) -> None:
        self.api_key = _resolve_key(api_key)
        self.base_url = base_url or os.environ.get("BYTNODE_BASE_URL") or DEFAULT_BASE_URL
        self.stream_url = stream_url or os.environ.get("BYTNODE_STREAM_URL") or DEFAULT_STREAM_URL
        self._transport = AsyncTransport(
            self.api_key, self.base_url, timeout, max_retries, default_headers, http_client=http_client
        )
        self._last_rate_limit = None
        self._init_resources()

    async def _request(
        self, route: RouteSpec, params: Mapping[str, Any], options: RequestOptions | None, *, body: Any = None
    ) -> Response[Any]:
        path, query = build_request(route, params)
        http, raw = await self._transport.request(route.method, path, query=query, body=body, options=options)
        return self._response(route, http, raw, partial=query.get("fields") is not None)

    def stream(
        self,
        *channels: str,
        depth: int | None = None,
        reconnect: bool = True,
        max_reconnects: int | None = None,
        open_timeout: float = 10.0,
    ) -> AsyncStream:
        """The real-time WebSocket stream: `async with client.stream(...) as s: async for msg in s`."""
        return AsyncStream(
            self.stream_url,
            self.api_key,
            list(channels),
            depth=depth,
            reconnect=reconnect,
            max_reconnects=max_reconnects,
            open_timeout=open_timeout,
        )

    async def close(self) -> None:
        """Release the HTTP connections."""
        await self._transport.aclose()

    async def __aenter__(self) -> AsyncBytnode:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        await self.close()

    def __repr__(self) -> str:
        return f"<AsyncBytnode base_url={self.base_url!r}>"


__all__ = ["AsyncBytnode", "Bytnode"]
