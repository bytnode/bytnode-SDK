# Changelog

All notable changes to the BytNode SDKs. Both packages share one version number.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

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
