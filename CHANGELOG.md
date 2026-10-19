# Changelog

All notable changes to the BytNode SDKs. Both packages share one version number.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [2.0.4] — 2026-10-19

Generated from contract `2.0.4`.

- 77 served pairs instead of 22: 75 USDT-margined perpetual markets plus the two stablecoin
  pairs. `KnownSymbol` now lists all 77 (`GET /v1/symbols` remains the source of truth).
- The 55 new pairs have no imported open-interest or basis history: `1m`–`30m` start on
  2026-10-19 09:31 UTC.

## [2.0.3] — 2026-10-16

Generated from contract `2.0.3`.

- CVD and buy/sell-ratio history no longer return zeros on older buckets: they carry the real
  buy and sell volumes of the bucket's own candle (the same as `trades_kline`), with
  `cvd_series` set to `None` / `null` where finer candles do not cover the bucket.
- New `buy_sell_coverage_ratio` on `Cvd`, `BuySellRatio` and `TradesKline`: the share of the
  volume whose buy/sell split is known (below 1 on part of the history).
- `CvdHistoryItem` is now the same type as `Cvd`; the old name remains as an alias.

## [2.0.2] — 2026-10-16

Generated from contract `2.0.2`.

- `client.status()` (`/v1/status`) now covers every data family: options, on-chain (BTC, ETH),
  macro, ETF, tokenomics and sentiment feeds join the market feeds. `StatusFeedsItem.feed` is the
  closed list of the 83 public feed names; `family` uses the names of `/v1/limits` (`trades`, no
  longer `ticks`).
- `age_s` and `is_stale` are typed optional (`None` / `null` when a feed could not be checked), as
  the API always answered.
- `/v1/oi/history`, `/v1/oi/change/history`, `/v1/basis/history`: each `timeframe` starts where the
  readings are at least that fine (`1h` from 2026-04-04, `4h` from 2025-10-07, `1m`–`30m` from
  2026-05-28), so `step` is always the real spacing; documented on the methods.

## [2.0.1] — 2026-10-16

Generated from contract `2.0.1`.

- `client.ws.token()` (`POST /v1/ws/token`): a short-lived WebSocket token (60 seconds, one
  connection) to open the stream without handing your API key to a web page.
- TypeScript stream: the API key never goes into a URL any more. New `token` option — a function
  returning a fresh token, typically from your backend — called before every connection and
  reconnection; the key is then not sent at all. Without the `ws` package (browser, Deno, Bun) and
  without `token`, the stream asks `POST /v1/ws/token` for a token instead of putting the key in
  `?api_key=`. With `ws` (Node), the key stays in the `X-API-KEY` header, as before.
- The API now refuses plain `http://` (403 `https_required`) instead of redirecting: the SDKs always
  used `https://`, nothing to change on your side.

## [2.0.0] — 2026-10-16

The reference version of the SDKs, generated from contract `2.0.0` (the reference version of
the API). Both packages share one version number with the contract's major.

- Typed clients for the 131 routes, the WebSocket stream (`frame` / `batch` modes, gap detection,
  reconnection) and typed errors, in Python and TypeScript.
- `is_volume_estimated` and its variants are optional: `None` / `null` when their volume is.
- Channel helpers: `trades`, `orderbook`, `liquidations`.
