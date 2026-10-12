# Changelog

All notable changes to the BytNode SDKs. Both packages share one version number.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [0.1.0] — unreleased

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
