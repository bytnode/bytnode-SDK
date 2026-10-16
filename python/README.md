# BytNode Python SDK

The official Python client of the [BytNode](https://bytnode.com) crypto market-data API: candles,
order flow, derivatives, liquidations, options, macro, on-chain and ETF data — typed, paginated for
you, one call away from a pandas DataFrame, plus the real-time WebSocket stream.

```bash
pip install https://github.com/bytnode/bytnode-SDK/releases/download/v2.0.2/bytnode-2.0.2-py3-none-any.whl
# with pandas: pip install "bytnode[pandas] @ https://github.com/bytnode/bytnode-SDK/releases/download/v2.0.2/bytnode-2.0.2-py3-none-any.whl"
export BYTNODE_API_KEY=cb_live_...   # create one at https://bytnode.com/dashboard/keys
```

```python
from bytnode import Bytnode

client = Bytnode()                                   # reads BYTNODE_API_KEY

last = client.klines("BTCUSDT", "1h")                # the latest CLOSED candle
print(last.data.close, last.data.time)               # typed model, datetimes in UTC

candles = client.klines.history("BTCUSDT", "1h", limit=24)   # most recent first
print(candles.data[0].close, len(candles))

from datetime import datetime, timedelta, timezone

since = datetime.now(timezone.utc) - timedelta(hours=12)                      # inside every plan's window
df = client.klines.history.iter("BTCUSDT", "1h", since=since).to_pandas()     # every page, one DataFrame (pip install pandas)

client.close()                                       # or: with Bytnode() as client: ...
```

Python 3.10+. Synchronous and `asyncio` clients. Fully typed (`py.typed`, mypy strict).

---

- [The rule: the URL is the method](#the-rule-the-url-is-the-method)
- [Responses](#responses)
- [History and pagination](#history-and-pagination)
- [pandas](#pandas)
- [Errors](#errors)
- [Retries, timeouts and rate limits](#retries-timeouts-and-rate-limits)
- [Snapshot: many fields in one call](#snapshot-many-fields-in-one-call)
- [Technical indicators](#technical-indicators)
- [Real-time WebSocket](#real-time-websocket)
- [Async](#async)
- [MCP and command line](#mcp-and-command-line)
- [Configuration](#configuration)

## The rule: the URL is the method

Every route of the [API reference](https://bytnode.com/docs) is an attribute named after its path:

| Route | Method |
|---|---|
| `GET /v1/klines` | `client.klines(symbol, timeframe)` — the latest closed candle |
| `GET /v1/klines/history` | `client.klines.history(symbol, timeframe, ...)` |
| `GET /v1/funding/rate` | `client.funding.rate(symbol)` |
| `GET /v1/funding/rate/history` | `client.funding.rate.history(symbol, ...)` |
| `GET /v1/buy-sell-ratio/spot` | `client.buy_sell_ratio.spot(symbol, timeframe)` |
| `GET /v1/options/max-pain/history` | `client.options.max_pain.history("BTC", "2026-12-25")` |
| `GET /v1/capabilities` | `client.capabilities("BTCUSDT")` |
| `GET /v1/global` | `client.global_()` (`global` is a Python keyword: a trailing `_`) |

Dashes become underscores; a Python keyword takes a trailing underscore. Required parameters come first and can be positional; the others are
keyword-only. Closed values are typed (`timeframe: Timeframe`, `asset: Asset`, `order: Order`):
your editor completes them, and a typo is flagged before the request is sent. Every method carries
the docstring of its route.

## Responses

A call returns a `Response`:

```python
resp = client.funding.rate("BTCUSDT")
resp.data            # FundingRate | None  — a model, a list of models, or None
resp.data.rate_pct   # (when resp.data is not None) attributes are the API's own field names
resp.server_time     # when the server answered (rows carry their own `time`)
resp.symbol          # effective symbol of the request (`resp.meta` holds the rest of the envelope)
resp.unavailable     # why `data` is empty: "not_applicable", "no_api_key" or "no_data"
resp.rate_limit      # your rate limit and monthly quota after this call
resp.raw             # the JSON body, untouched
```

A list response iterates and indexes like a list (`for row in resp`, `resp[0]`, `len(resp)`).
Models also read like mappings (`row["close"]`, `row.get("volume_spot")`) and convert back with
`row.to_dict()` or `resp.to_dicts()`. Dates are `datetime` objects in UTC.

A field added by the API after this release is kept as an extra attribute: a newer API never breaks
an older SDK. If a response ever does not match its model, it is returned unvalidated with a
`BytnodeWarning` instead of raising.

## History and pagination

History routes take time bounds as you write them — `datetime` (naive = UTC), `date`, an ISO string
or epoch milliseconds:

```python
from datetime import datetime, timedelta, timezone

now = datetime.now(timezone.utc)
page = client.funding.rate.history("BTCUSDT", since=now - timedelta(days=5), until=now, limit=100)
page.next   # relative URL of the following page, or None (iter() follows it for you)
```

`.iter()` follows `next` for you, page after page, and yields rows lazily:

```python
from datetime import datetime, timedelta, timezone

for row in client.klines.history.iter("ETHUSDT", "4h", since=datetime.now(timezone.utc) - timedelta(days=3)):
    ...

rows = client.oi.history.iter("BTCUSDT", "1h", since=now - timedelta(hours=12), max_items=500).to_list()
```

- With `since`, pages are as large as the route allows (fewest requests, least quota); without it, the route's default page, which stops at your plan's history window instead of exceeding it. `page_size=` changes it.
- With `since`, rows come oldest first (`order="asc"`); without, most recent first.
- `.pages()` yields each page's `Response` (rate limit, `server_time`...).
- An integer that looks like seconds is refused: `since=1767225600` raises with the millisecond value
  to use instead.

How far back you can read depends on your plan (a `PermissionDeniedError` with code
`history_depth` says so).

## pandas

```python
# `to_pandas()` needs pandas: pip install pandas (or install the wheel with the [pandas] extra)
from datetime import datetime, timedelta, timezone

df = client.klines.history.iter("BTCUSDT", "1d", since=datetime.now(timezone.utc) - timedelta(days=29)).to_pandas()  # inside the Free plan's 30-day daily window
df["close"].pct_change().rolling(7).std()  # 7-day volatility
```

`to_pandas()` exists on every response and iterator: indexed by `time` (UTC), ascending, one column
per field. `flatten=True` spreads nested objects into dotted columns. Install the extra:
the `pandas` extra (`bytnode[pandas]`, see Install).

## Errors

```python
from bytnode import InvalidRequestError, PermissionDeniedError, RateLimitError

try:
    client.klines("BTCUSD", "1h")
except InvalidRequestError as e:      # 400 / 422
    print(e.code, e.param, e.message) # invalid_symbol symbol "Unknown symbol 'BTCUSD'. Accepted values: ..."
```

| Exception | When | Useful attributes |
|---|---|---|
| `InvalidRequestError` | 400 / 422: a parameter is wrong | `code`, `param`, `message` (says what is accepted) |
| `AuthenticationError` | 401: key missing, invalid or revoked | |
| `PermissionDeniedError` | 403: outside your plan | `code` (`plan_family`, `history_depth`, `plan_websocket`), `details` |
| `NotFoundError` | 404: unknown or retired route | `message` names the replacement |
| `RateLimitError` | 429 | `retry_after`, `is_quota` |
| `ServerError` | 5xx (after retries) | `status` |
| `APIConnectionError` / `APITimeoutError` | no answer | |
| `MissingAPIKeyError` | no key at all | |
| `StreamError` / `ConnectionLimitError` | WebSocket | `code`, `close_code` |

All inherit from `bytnode.BytnodeError`; HTTP ones from `bytnode.APIError` (`status`, `code`,
`message`, `param`, `details`, `reason`, `headers`, `body`). Branch on `e.code` — stable, listed in
`bytnode.types.ErrorCode` — never on the message. Every error carries `request_id` (quote it to
support). A value the SDK checks before sending (an indicator parameter out of range, a time in
seconds instead of milliseconds) raises a plain `ValueError` at once, without a request: it is a bug
in the calling code, not an API answer. Closed values such as `timeframe` are typed (`mypy` refuses
`"60m"`); sent anyway, they come back from the API as a 422 (`invalid_timeframe`, with the accepted
values). If the API serves another MAJOR contract than the SDK, or a newer MINOR one
(additions the SDK does not type yet), a `BytnodeWarning` says so once.

## Retries, timeouts and rate limits

The SDK retries what is worth retrying, with exponential backoff and jitter:

- 429 rate limit: waits `Retry-After` (up to 60 s), then retries;
- 502, 503, 504 and network errors: up to `max_retries` times (default 3);
- 500: once;
- a spent **monthly quota** is never retried: `RateLimitError` with `is_quota=True` at once.

```python
client = Bytnode(timeout=10, max_retries=5)
client.klines.history("BTCUSDT", "1m", request_options={"timeout": 60, "max_retries": 0})

client.last_rate_limit    # RateLimit(limit=600, remaining=598, reset_s=1, quota_limit=..., quota_remaining=...)
```

## Snapshot: many fields in one call

`GET /v1/snapshot` returns many fields for one symbol in a single request (from the Traders plan).
A field without a timeframe is the OBJECT of its route (`True` or `1`); a multi-timeframe
field takes a mapping `{timeframe: N}` and is ALWAYS a list of the N latest closed buckets:

```python
snap = client.snapshot("BTCUSDT", funding_rate=True, basis=True, klines={"1h": 24, "1d": 7},
                       buy_sell_ratio={"5m": 12})
funding = snap.data.funding_rate     # the object of /v1/funding/rate, or None
bars = snap.data.klines_1h           # list[KlineHistoryItem] | None, most recent first
print(bars[0].close if bars else None)
client.snapshot.catalog("BTCUSDT").data.available_fields
```

## Technical indicators

```python
from bytnode import indicators as ind

res = client.indicators("BTCUSDT", "1h", [ind.rsi(14), ind.macd(), ind.bb(20, std=2.5)], limit=200)
res.data.indicators["rsi_14"].values[0]   # IndicatorRow(time=..., value=...): rows newest first
res.data.indicators["macd_12_26_9"].values[0].signal  # named outputs of a multi-output indicator
res.to_pandas()                           # one column per output (macd_12_26_9.signal...), indexed by candle time
```

Builders are typed and check their bounds locally; ids are generated (`rsi_14`) or given
(`ind.rsi(7, id="fast")`). Plain dicts work too: `{"type": "ema", "period": 50}`.

## Real-time WebSocket

```python
from bytnode import channels as ch

with client.stream(ch.trades("BTCUSDT"), ch.orderbook("BTCUSDT"), depth=5) as stream:
    for msg in stream:
        if msg.kind == "orderbook":
            print(msg.data.avg_mid_price, msg.data.bids[0])
        else:
            for trade in msg.data:
                print(trade.side, trade.price, trade.quantity)
        if msg.gap:
            print(f"{msg.gap} message(s) lost before this one on {msg.channel}")
```

- Channels: `ch.trades(symbol, market="futures"|"spot")`, `ch.orderbook(symbol, market=...)`,
  `ch.liquidations(symbol)` — or the raw names (`trades.futures.BTCUSDT`, case-insensitive).
- **Reconnects by itself** with backoff and subscribes again; `stream.reconnects` counts it.
  A refused key, a plan without the stream or the connection ceiling of your plan are raised, not
  retried.
- `msg.gap` counts the messages lost just before `msg` on an event channel (a jump in `seq`).
- `stream.subscribe(...)` / `stream.unsubscribe(...)` change the subscription on the fly
  (all or nothing: one bad channel, none applied).
- Messages are typed: `TradesMessage`, `LiquidationsMessage`, `BookMessage`.

## Async

`AsyncBytnode` has the same methods, awaited; `.iter()` becomes `async for`, the stream
`async with` / `async for`:

```python
import asyncio
from datetime import datetime, timedelta, timezone

from bytnode import AsyncBytnode, channels as ch

async def main() -> None:
    async with AsyncBytnode() as client:
        btc, eth = await asyncio.gather(client.funding.rate("BTCUSDT"), client.funding.rate("ETHUSDT"))
        since = datetime.now(timezone.utc) - timedelta(hours=12)
        df = await client.klines.history.iter("BTCUSDT", "1h", since=since).to_pandas()
        async with client.stream(ch.trades("BTCUSDT")) as stream:
            async for msg in stream:
                ...

asyncio.run(main())
```

## MCP and command line

The package installs a `bytnode` command:

```bash
bytnode check                         # key valid? latency? rate limit and quota left?
bytnode mcp install cursor            # add the BytNode MCP server to Cursor
bytnode mcp install claude-desktop    # ... or claude-code, vscode, windsurf
bytnode mcp config vscode             # print the snippet to paste by hand (key masked)
```

`mcp install` merges the `bytnode` server into the client's config (a backup is written first) so an
AI agent can query BytNode with your key. From Python: `bytnode.mcp.install("cursor")`.

## Configuration

| Argument | Environment | Default |
|---|---|---|
| `api_key` | `BYTNODE_API_KEY` | — |
| `base_url` | `BYTNODE_BASE_URL` | `https://api.bytnode.com` |
| `stream_url` | `BYTNODE_STREAM_URL` | `wss://api.bytnode.com/ws` |
| `timeout` | | 30 s per attempt |
| `max_retries` | | 3 |
| `default_headers` | | |
| `http_client` | | your own `httpx.Client` / `httpx.AsyncClient` (proxies, TLS...) |

Use the client as a context manager, or call `close()`, to release its connections.

## Links

- Documentation: https://bytnode.com/docs
- OpenAPI contract: https://api.bytnode.com/openapi.json
- Changelog of the API: https://bytnode.com/docs/changelog
- Source and issues: https://github.com/bytnode/bytnode-SDK

MIT licensed (the code of this SDK; the data stays under your BytNode subscription).
