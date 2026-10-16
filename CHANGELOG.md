# Changelog

All notable changes to the BytNode SDKs. Both packages share one version number.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

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
