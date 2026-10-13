# Changelog

All notable changes to the BytNode SDKs. Both packages share one version number.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [0.3.0] — 2026-10-13

Generated from contract `2.6.0` (additions only since 2.0.0).

### Changed (TypeScript types — why this is 0.3.0, not a patch)

- The generated models no longer carry an index signature (`[extra: string]: unknown`): a
  misspelt field (`row.rate_pc`) is now a compile error, as it is with mypy in Python. A field
  the API adds after this release is still in `response.raw`.

### Added

- `response.request_id` (Python) / `response.requestId` (TypeScript): the `X-Request-Id` of the
  call, on every response, not only on errors.
- `client.limits()`: `rate.per_minute`; `ticks_window_minutes` and `liquidation_events` are `0`
  when your plan does not include their family (`null` = unlimited).
- Per-second trade candles carry `net_volume`, `avg_trade_size`, `trade_rate` and
  `is_volume_estimated`, like every other trade candle.

## [0.2.4] — 2026-10-13

Generated from contract `2.5.0` (additions only since 2.0.0).

### Fixed

- `.iter()` follows `next` until it is `null`: it stopped on an EMPTY page, while the API can
  return a short or empty page that still has a `next` (an ascending or descending read that
  reaches a dense period returns, within its time budget, what it has read so far).
- `.iter()` asks a page again with half the rows (down to 10) when the API answers 504
  `upstream_timeout`, instead of failing the whole read.
- TypeScript: the API key is no longer serialized with the client (`JSON.stringify(client)`,
  `{ ...client }`, `console.log(client)` in Node). `client.apiKey` still reads it.
- TypeScript: the browser guard no longer says the API sends no CORS headers (it does).

### Changed

- Fields that are `null` on the OLDEST rows of a history (daily candles before 2023-10, early
  on-chain, options and macro rows) are typed as optional values; `error.details` is typed.

## [0.2.3] — 2026-10-13

Generated from contract `2.4.0` (additions only since 2.0.0).

### Fixed

- A snapshot field that only accepts depth 1 (`funding_rate`, `fear_greed`, `options_summary`…) is
  typed as its route's object (or `None`/`null`) in both SDKs, as the README says; its depth
  parameter accepts `True`/`1` only.
- `client.limits()`: `families` is a list of strings, `rate` and `quota` are objects (they were
  typed as numbers or strings, and a paid key's answer failed validation).
- `.iter(since=…)` reads every row: the API no longer stops an ascending read at the first gap
  of the series (options, inter-venue spread, funding).

### Changed

- `ErrorCode` lists the known codes; an error code the SDK does not know yet is kept as a string.
- The model of `/v1/symbols` rows is `SymbolInfo` (was `Symbol`, which shadowed the global
  `Symbol` of JavaScript).

## [0.2.2] — 2026-10-13

Generated from contract `2.2.0` (additions only since 2.0.0: no route, field or value removed or renamed).

### Changed

- `.iter()` without `since` no longer asks for the route's maximum page (`limit=1000`): it uses the
  route's default page, which stops at your plan's history window instead of being refused with
  403 `history_depth` on a small plan. With `since`, pages stay as large as the route allows.
- A snapshot field that only accepts depth 1 is typed as its route's object (or `null`), no longer
  `T | T[]`.
- `data.indicators` of `POST /v1/indicators` is typed as a mapping `id -> IndicatorResult`.
- The model of `/v1/global/history` rows is `GlobalMarketHistoryItem` (was `GlobalHistoryItem`), like
  `GlobalMarket` for `/v1/global`.

### Fixed

- README: `options.max_pain.history(asset, expiry)` argument order, `next` is a relative URL, the
  values checked locally (indicator parameters, seconds) versus those the API refuses (`timeframe`),
  snapshot typing, and examples that run on the free plan.

## [0.2.1] — 2026-10-13

Generated from contract `2.0.0` as republished on 2026-10-13 (same routes, more precise schemas).

### Changed

- Rows are typed with the fields of every variant the API serves: `eth_holdings` (ETF, `asset=ETH`),
  the four `dataset` shapes of `btc.mining.history`, the stablecoin keys of `symbols.capabilities`.
- Nullability follows the contract (`priced_at`, `is_volume_futures_estimated` and a few labels can be
  `null`).
- `Response.unavailable` is a mapping field -> reason on the snapshot; the obsolete `coverage`
  attribute is gone (the API no longer sends it).
- `to_pandas()` without pandas says `pip install pandas` (the PyPI extra does not exist yet).

### Added

- A one-time `BytnodeWarning` (a console warning in TypeScript) when the API serves another major
  contract version than the SDK.

## [0.2.0] — 2026-10-12

Generated from contract `2.0.0` (129 routes). Breaking, like the contract it follows.

### Changed

- Routes follow the API's 2026-10-12 names: executions are `client.trades.spot` /
  `client.trades.futures` / `client.trades.large` (were `client.ticks.*`), candles built from trades
  are `client.trades_kline*` (`client.tradesKline*` in TypeScript); the market is in the path
  (`client.cvd.spot(...)`, `client.orderbook.futures(...)`), there is no `market` parameter any more.
- Models are named by the contract itself (`Trade`, `TradesKline`, `Oi`, `Limits`...).
- Closed sets of values come from the contract's `enum`s: new `Asset`, `IntradayTimeframe`,
  `CoarseTimeframe` literals; `Market` and `BookMarket` are gone.
- The snapshot field `global` is the `global_market` argument in Python (`global` is a keyword).
- Stream messages follow the current frames: `server_time` on the message (was `time`; each row
  keeps its `time`), `value_usd` (was `usd_value`), `avg_spread_bps` (was `spread_bps_avg`).
- Candle volumes: `volume` is spot + futures, `volume_spot` / `volume_futures` the parts.

### Added

- `client.limits()`: the plan, rate, monthly quota and history windows of your key (not counted).
- `client.oi(...)`: the current open interest.
- `request_id` on every error (from `X-Request-Id`): quote it to support.

### Install

From the release assets (`bytnode-0.2.0-py3-none-any.whl`, `bytnode-0.2.0.tgz`); not on PyPI/npm yet.

## [0.1.0] — 2026-10-12 (not published)

First release, generated from contract `1.2.0`.

### Python (`bytnode`) and TypeScript (`bytnode`)

- All 111 REST routes, named after their path, with typed parameters and typed models.
- `.iter()` on every paginated history: follows `next`, largest pages, oldest first with `since`.
- Time bounds as `datetime` / `Date`, ISO strings or epoch milliseconds (seconds are refused).
- Typed errors with the stable `code`, `param` and `reason`; automatic retries with backoff,
  `Retry-After` respected, a spent monthly quota never retried.
- Rate-limit and monthly-quota headers parsed on every response (`rate_limit` / `rateLimit`).
- `snapshot()` with typed fields and depths, `snapshot.catalog()`.
- `indicators()` with typed, locally checked builders (`ind.rsi(14)`...).
- WebSocket stream: automatic reconnection and re-subscription, typed messages, loss detection.
- `bytnode check` and `bytnode mcp install|config` command line.
- Python: sync and asyncio clients, `.to_pandas()`, mypy strict.
- TypeScript: ESM + CommonJS, Node 18+ / Deno / Bun, refuses to run in a browser unless told to.
