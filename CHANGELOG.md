# Changelog

All notable changes to the BytNode SDKs. Both packages share one version number.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [2.0.0] — 2026-10-16

The reference version of the SDKs, generated from contract `2.0.0` (the reference version of
the API). Both packages share one version number with the contract's major.

- Typed clients for the 131 routes, the WebSocket stream (`frame` / `batch` modes, gap detection,
  reconnection) and typed errors, in Python and TypeScript.
- `is_volume_estimated` and its variants are optional: `None` / `null` when their volume is.
- Channel helpers: `trades`, `orderbook`, `liquidations`.
