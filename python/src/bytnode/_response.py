"""Responses, row iterators and the pandas bridge."""

from __future__ import annotations

import warnings
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from ._ratelimit import RateLimit
from ._routes import RouteSpec
from ._time import TIMEFRAME_MS

if TYPE_CHECKING:
    import pandas as pd

T = TypeVar("T")

CURSOR_KEYS = ("since_ms", "until_ms", "before_ms", "after_id", "order")


_CONTRAT_SIGNALE = False


def _verifier_contrat(headers: Mapping[str, str]) -> None:
    """Warn once when the API serves another MAJOR contract version than this SDK."""
    global _CONTRAT_SIGNALE
    servi = headers.get("bytnode-contract-version") or headers.get("BytNode-Contract-Version")
    if _CONTRAT_SIGNALE or not servi:
        return
    from ._generated.routes import API_VERSION

    if servi.split(".")[0] != API_VERSION.split(".")[0]:
        _CONTRAT_SIGNALE = True
        warnings.warn(
            f"bytnode: the API serves contract {servi}, this SDK was generated for {API_VERSION}. "
            "Upgrade the SDK (https://bytnode.com/docs/sdk).",
            BytnodeWarning,
            stacklevel=3,
        )


class BytnodeWarning(UserWarning):
    """A response did not match the SDK's model (it was returned unvalidated)."""


_warned: set[str] = set()


def _lenient(model: type[BaseModel], obj: Mapping[str, Any]) -> BaseModel:
    """Build a model WITHOUT validation, mapping wire aliases to attribute names."""
    by_alias = {info.alias: name for name, info in model.model_fields.items() if info.alias}
    return model.model_construct(**{by_alias.get(k, k): v for k, v in obj.items()})


def parse_row(model: type[BaseModel] | None, obj: Any, *, partial: bool = False) -> Any:
    """One row of `data` as its model; never raises on a contract drift."""
    if model is None or not isinstance(obj, Mapping):
        return obj
    if partial:
        return _lenient(model, obj)
    try:
        return model.model_validate(obj)
    except PydanticValidationError as exc:
        if model.__name__ not in _warned:
            _warned.add(model.__name__)
            warnings.warn(
                f"bytnode: a {model.__name__} row did not match the SDK model and was returned unvalidated "
                f"({exc.error_count()} error(s), first: {exc.errors()[0].get('loc')} {exc.errors()[0].get('msg')}). "
                "Upgrading bytnode usually fixes it.",
                BytnodeWarning,
                stacklevel=4,
            )
        return _lenient(model, obj)


def _to_plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(by_alias=True, mode="python")
    return value


class Response(Generic[T]):
    """One API response.

    Attributes:
        data: the payload — a model, a list of models, or `None` (see `unavailable`).
        server_time: when the server answered (not the time of the data: rows carry `time`).
        data_type: stable name of the payload.
        meta: the other keys of the envelope (`symbol`, `timeframe`, `asset`, `market`...).
        unavailable: why `data` is empty (`not_applicable`, `no_api_key`, `no_data`), or `None`;
            on the snapshot, a mapping field -> reason.
        next: the parameters of the following page (`None` = last page). `.iter()` follows it for you.
        rate_limit: your rate limit and monthly quota after this request.
        raw: the decoded JSON body, untouched.
    """

    __slots__ = (
        "data",
        "data_type",
        "headers",
        "meta",
        "next",
        "partial",
        "rate_limit",
        "raw",
        "route",
        "server_time",
        "status_code",
        "unavailable",
    )

    def __init__(
        self,
        data: T,
        *,
        raw: dict[str, Any],
        route: RouteSpec,
        status_code: int,
        headers: Mapping[str, str],
    ) -> None:
        self.data = data
        self.raw = raw
        self.route = route
        self.status_code = status_code
        self.headers = headers
        st = raw.get("server_time")
        self.server_time: datetime | None = (
            datetime.fromisoformat(st.replace("Z", "+00:00")) if isinstance(st, str) else None
        )
        self.data_type: str | None = raw.get("data_type")
        self.unavailable: str | dict[str, str] | None = raw.get("unavailable")
        self.partial: bool | None = raw.get("partial")
        self.next: dict[str, Any] | str | None = raw.get("next")
        skip = {"status", "server_time", "data_type", "data", "next", "unavailable", "partial"}
        _verifier_contrat(headers)
        self.meta: dict[str, Any] = {k: v for k, v in raw.items() if k not in skip}
        self.rate_limit: RateLimit | None = RateLimit.from_headers(headers)

    # ---- conveniences --------------------------------------------------------

    @property
    def symbol(self) -> str | None:
        return self.meta.get("symbol")

    @property
    def timeframe(self) -> str | None:
        return self.meta.get("timeframe")

    def __iter__(self) -> Iterator[Any]:
        if isinstance(self.data, list):
            return iter(self.data)
        return iter([] if self.data is None else [self.data])

    def __len__(self) -> int:
        if isinstance(self.data, list):
            return len(self.data)
        return 0 if self.data is None else 1

    def __getitem__(self, index: int) -> Any:
        if isinstance(self.data, list):
            return self.data[index]
        raise TypeError("this response holds a single object: read .data")

    def __repr__(self) -> str:
        size = f"rows={len(self.data)}" if isinstance(self.data, list) else f"data={type(self.data).__name__}"
        extra = f" unavailable={self.unavailable!r}" if self.unavailable else ""
        return f"<Response {self.data_type or self.route.path} {size}{extra}>"

    def to_dicts(self) -> list[dict[str, Any]]:
        """The rows as plain dicts keyed by the API's field names."""
        if self.route.shape == "snapshot" and self.data is not None:
            return [_to_plain(self.data)]
        return [_to_plain(r) for r in self]

    def to_pandas(self, *, flatten: bool = False, index: str | None = "time") -> pd.DataFrame:
        """The rows as a `pandas.DataFrame`, indexed by `time` (UTC) in ascending order.

        `flatten=True` spreads nested objects into dotted columns (`context.gold_usd`).
        `POST /v1/indicators` gives one column per output, indexed by candle time.
        Needs pandas (`pip install pandas`).
        """
        if self.route.shape == "indicators":
            return _indicators_frame(self)
        return rows_to_frame(self.to_dicts(), flatten=flatten, index=index)


def _require_pandas() -> Any:
    try:
        import pandas as pd
    except ImportError:  # pragma: no cover - depends on the environment
        raise ImportError("to_pandas() needs pandas: pip install pandas") from None
    return pd


def rows_to_frame(rows: list[dict[str, Any]], *, flatten: bool = False, index: str | None = "time") -> pd.DataFrame:
    pd = _require_pandas()
    frame = pd.json_normalize(rows) if flatten else pd.DataFrame(rows)
    if index and index in frame.columns:
        frame[index] = pd.to_datetime(frame[index], utc=True)
        frame = frame.set_index(index).sort_index()
    return frame


def _indicators_frame(resp: Response[Any]) -> pd.DataFrame:
    pd = _require_pandas()
    data = resp.data
    indicators = getattr(data, "indicators", None) or {}
    step = TIMEFRAME_MS.get(resp.timeframe or "", 0)
    columns: dict[str, list[Any]] = {}
    last_time = None
    length = 0
    for ident, ind in indicators.items():
        values = ind.values if hasattr(ind, "values") else ind.get("values")
        last_time = getattr(ind, "time", None) or last_time
        if isinstance(values, dict):
            for key, series in values.items():
                columns[f"{ident}.{key}"] = list(series)
                length = max(length, len(series))
        else:
            columns[ident] = list(values or [])
            length = max(length, len(values or []))
    # every series ends on the same candle: right-align them
    for key, series in columns.items():
        columns[key] = [None] * (length - len(series)) + series
    frame = pd.DataFrame(columns)
    if last_time is not None and step:
        end = pd.Timestamp(last_time)
        frame.index = pd.DatetimeIndex(
            [end - pd.Timedelta(milliseconds=step * (length - 1 - i)) for i in range(length)], name="time"
        )
    return frame


# --------------------------------------------------------------------------- iterators


def next_params(params: dict[str, Any], nxt: Mapping[str, Any] | str) -> dict[str, Any]:
    """The parameters of the following page: the cursor of `next` replaces ours.

    `next` is an object of parameters today; a URL (`/v1/klines?symbol=...&before_ms=...`) is
    understood too, so a future form of the API keeps paginating.
    """
    if isinstance(nxt, str):
        from urllib.parse import parse_qsl, urlsplit

        query = dict(parse_qsl(urlsplit(nxt).query))
        return {**{k: v for k, v in params.items() if k == "fields"}, **query}
    out = {k: v for k, v in params.items() if k not in CURSOR_KEYS}
    out.update({k: v for k, v in nxt.items() if v is not None})
    return out


# A page the API could not compute in time (504 `upstream_timeout`) is asked again
# with half the rows, down to `_MIN_PAGE`: a long read never dies on one heavy page.
_SHRINKS = 4
_MIN_PAGE = 10


def _is_timeout(exc: Exception) -> bool:
    from ._errors import ServerError

    return isinstance(exc, ServerError) and (
        getattr(exc, "status", None) == 504 or getattr(exc, "code", None) == "upstream_timeout"
    )


def _smaller(params: dict[str, Any]) -> dict[str, Any] | None:
    limit = params.get("limit")
    if not isinstance(limit, int) or limit <= _MIN_PAGE:
        return None
    return {**params, "limit": max(_MIN_PAGE, limit // 2)}


def _fetch_shrinking(
    fetch: Callable[[dict[str, Any]], Response[list[T]]], params: dict[str, Any]
) -> tuple[Response[list[T]], dict[str, Any]]:
    for _ in range(_SHRINKS):
        try:
            return fetch(params), params
        except Exception as exc:
            smaller = _smaller(params) if _is_timeout(exc) else None
            if smaller is None:
                raise
            params = smaller
    return fetch(params), params


async def _afetch_shrinking(
    fetch: Callable[[dict[str, Any]], Awaitable[Response[list[T]]]], params: dict[str, Any]
) -> tuple[Response[list[T]], dict[str, Any]]:
    for _ in range(_SHRINKS):
        try:
            return await fetch(params), params
        except Exception as exc:
            smaller = _smaller(params) if _is_timeout(exc) else None
            if smaller is None:
                raise
            params = smaller
    return await fetch(params), params


class _IterBase(Generic[T]):
    def __init__(self, route: RouteSpec, params: dict[str, Any], max_items: int | None) -> None:
        self._route = route
        self._params = params
        self._max = max_items

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self._route.path} {self._params}>"


class RowIterator(_IterBase[T]):
    """Every row of a period, fetched page after page as you iterate.

    `for row in client.klines.iter(...)`, or collect with `.to_list()` / `.to_pandas()`.
    `.pages()` yields the `Response` of each page (rate limit, `server_time`...).
    """

    def __init__(
        self,
        fetch: Callable[[dict[str, Any]], Response[list[T]]],
        route: RouteSpec,
        params: dict[str, Any],
        max_items: int | None = None,
    ) -> None:
        super().__init__(route, params, max_items)
        self._fetch = fetch

    def pages(self) -> Iterator[Response[list[T]]]:
        params, seen = dict(self._params), 0
        while True:
            page, params = _fetch_shrinking(self._fetch, params)
            yield page
            seen += len(page)
            # Only `next: null` ends the read: a page can be short, even empty, and
            # still have a `next` (an ascending read that reached a dense period).
            if not page.next or (self._max is not None and seen >= self._max):
                return
            new = next_params(params, page.next)
            if new == params:  # a cursor that does not move would loop forever
                return
            params = new

    def __iter__(self) -> Iterator[T]:
        count = 0
        for page in self.pages():
            for row in page:
                if self._max is not None and count >= self._max:
                    return
                count += 1
                yield row

    def to_list(self) -> list[T]:
        return list(self)

    def to_pandas(self, *, flatten: bool = False, index: str | None = "time") -> pd.DataFrame:
        """Every row as one DataFrame indexed by `time`, ascending. Needs pandas."""
        return rows_to_frame([_to_plain(r) for r in self], flatten=flatten, index=index)


class AsyncRowIterator(_IterBase[T]):
    """Async twin of `RowIterator`: `async for row in client.klines.iter(...)`,
    `await it.to_list()`, `await it.to_pandas()`."""

    def __init__(
        self,
        fetch: Callable[[dict[str, Any]], Awaitable[Response[list[T]]]],
        route: RouteSpec,
        params: dict[str, Any],
        max_items: int | None = None,
    ) -> None:
        super().__init__(route, params, max_items)
        self._fetch = fetch

    async def pages(self) -> AsyncIterator[Response[list[T]]]:
        params, seen = dict(self._params), 0
        while True:
            page, params = await _afetch_shrinking(self._fetch, params)
            yield page
            seen += len(page)
            if not page.next or (self._max is not None and seen >= self._max):
                return
            new = next_params(params, page.next)
            if new == params:
                return
            params = new

    async def __aiter__(self) -> AsyncIterator[T]:
        count = 0
        async for page in self.pages():
            for row in page:
                if self._max is not None and count >= self._max:
                    return
                count += 1
                yield row

    async def to_list(self) -> list[T]:
        return [row async for row in self]

    async def to_pandas(self, *, flatten: bool = False, index: str | None = "time") -> pd.DataFrame:
        return rows_to_frame([_to_plain(r) for r in await self.to_list()], flatten=flatten, index=index)
