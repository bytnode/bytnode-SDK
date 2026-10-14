"""Base classes of the generated resources: they hand every call to the client core."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from ._indicator_spec import IndicatorSpec, indicators_body
from ._response import AsyncRowIterator, Response, RowIterator
from ._routes import RouteSpec
from ._types import Depth, RequestOptions

if TYPE_CHECKING:
    from ._client import AsyncBytnode, Bytnode


def _iter_params(route: RouteSpec, params: dict[str, Any], page_size: int | None) -> dict[str, Any]:
    out = {k: v for k, v in params.items() if v is not None}
    if page_size is not None:
        if page_size < 1 or (route.max_limit and page_size > route.max_limit):
            raise ValueError(f"page_size must be between 1 and {route.max_limit}")
        out["limit"] = page_size
    elif route.max_limit and ("since_ms" in out or route.range_mode):
        # The largest pages (fewest requests, least quota) when the period is
        # bounded by `since`. Without it, the route's own default page: it stops
        # at your plan's history window, where `limit=1000` would be refused
        # with 403 `history_depth` on a small plan.
        out["limit"] = route.max_limit
    if "order" not in out:
        if "since_ms" in out:
            out["order"] = "asc"  # a period read from its start comes in chronological order
        elif route.range_mode:
            out["order"] = "desc"  # ticks only paginate in range reading
    return out


def _snapshot_query(symbol: str, fields: Mapping[str, Depth | None]) -> dict[str, Any]:
    query: dict[str, Any] = {"symbol": symbol}
    for wire, depth in fields.items():
        if depth is None or depth is False:
            continue
        if depth is True:
            query[wire] = "true"
        elif isinstance(depth, int) and depth >= 1:
            query[wire] = depth
        else:
            raise ValueError(f"snapshot field {wire}: depth must be True or an integer >= 1, got {depth!r}")
    if len(query) == 1:
        raise ValueError(
            "snapshot: ask for at least one field, e.g. client.snapshot('BTCUSDT', funding_rate=True). "
            "client.snapshot.catalog(symbol) lists them."
        )
    return query


class SyncResource:
    def __init__(self, client: Any) -> None:
        self._client: Bytnode = client

    def _call(self, route: RouteSpec, params: dict[str, Any], options: RequestOptions | None) -> Response[Any]:
        return self._client._request(route, params, options)

    def _iter(
        self,
        route: RouteSpec,
        params: dict[str, Any],
        *,
        page_size: int | None,
        max_items: int | None,
        request_options: RequestOptions | None,
    ) -> RowIterator[Any]:
        return RowIterator(
            lambda p: self._client._request(route, p, request_options),
            route,
            _iter_params(route, params, page_size),
            max_items,
        )

    def _snapshot(
        self, route: RouteSpec, symbol: str, fields: Mapping[str, Depth | None], options: RequestOptions | None
    ) -> Response[Any]:
        return self._client._request(route, _snapshot_query(symbol, fields), options)

    def _catalog(self, route: RouteSpec, symbol: str, options: RequestOptions | None) -> Response[Any]:
        return self._client._request(route, {"symbol": symbol}, options)

    def _indicators(
        self,
        route: RouteSpec,
        symbol: str,
        timeframe: str,
        indicators: Sequence[IndicatorSpec | Mapping[str, Any]],
        limit: int | None,
        options: RequestOptions | None,
    ) -> Response[Any]:
        body: dict[str, Any] = {"symbol": symbol, "timeframe": timeframe, "indicators": indicators_body(indicators)}
        if limit is not None:
            body["limit"] = limit
        return self._client._request(route, {}, options, body=body)


class AsyncResource:
    def __init__(self, client: Any) -> None:
        self._client: AsyncBytnode = client

    async def _call(self, route: RouteSpec, params: dict[str, Any], options: RequestOptions | None) -> Response[Any]:
        return await self._client._request(route, params, options)

    def _iter(
        self,
        route: RouteSpec,
        params: dict[str, Any],
        *,
        page_size: int | None,
        max_items: int | None,
        request_options: RequestOptions | None,
    ) -> AsyncRowIterator[Any]:
        return AsyncRowIterator(
            lambda p: self._client._request(route, p, request_options),
            route,
            _iter_params(route, params, page_size),
            max_items,
        )

    async def _snapshot(
        self, route: RouteSpec, symbol: str, fields: Mapping[str, Depth | None], options: RequestOptions | None
    ) -> Response[Any]:
        return await self._client._request(route, _snapshot_query(symbol, fields), options)

    async def _catalog(self, route: RouteSpec, symbol: str, options: RequestOptions | None) -> Response[Any]:
        return await self._client._request(route, {"symbol": symbol}, options)

    async def _indicators(
        self,
        route: RouteSpec,
        symbol: str,
        timeframe: str,
        indicators: Sequence[IndicatorSpec | Mapping[str, Any]],
        limit: int | None,
        options: RequestOptions | None,
    ) -> Response[Any]:
        body: dict[str, Any] = {"symbol": symbol, "timeframe": timeframe, "indicators": indicators_body(indicators)}
        if limit is not None:
            body["limit"] = limit
        return await self._client._request(route, {}, options, body=body)
