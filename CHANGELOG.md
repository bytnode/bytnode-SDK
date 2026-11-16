# Changelog

All notable changes to the BytNode SDKs. Both packages share one version number.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [1.1.0] — unreleased

Generated from contract `1.1.0`: computed market sentiment (144 routes).

- `sentiment` (every sentiment indicator of a pair: score, state, one-sentence meaning,
  confidence, drivers, sub-indicators, and a summary), `sentiment.history`,
  `sentiment.market` (breadth, market Fear & Greed, market phase), `sentiment.market.history`,
  `sentiment.screener` (every pair's value of one indicator, filtered by state) and
  `sentiment.methodology` (formulas, weights and the rule of every state).

## [1.0.1] — 2026-11-08

Generated from contract `1.0.1`.

- Liquidations name their venues: `venue` on each event (`liquidations.events`), `venues` (the
  venues summed in the row) on `liquidations.cumulative`, `liquidations.cumulative.history`,
  `liquidations.big_small_ratio` and `liquidations.big_small_ratio.history`.

## [1.0.0] — 2026-11-07

A new starting point, generated from contract `1.0.0`. Earlier SDK releases are withdrawn.

- **Breaking:** `safe_gas_price_gwei`, `propose_gas_price_gwei` and `fast_gas_price_gwei`
  are removed from `EthGas` and `EthGasHistoryItem` (`eth.gas`, `eth.gas.history`). Use
  `base_fee_gwei` and `gas_used_ratio`.
- Ethereum history goes back further: total supply and market cap since 2015-07-30; burnt
  fees, deflation and gas since the London upgrade (2021-08-05). On older days the supply
  breakdown (`execution_issuance_cumulative`, `consensus_rewards_cumulative`,
  `burnt_fees_cumulative`, `withdrawn_cumulative`) can be `None` / `null`.
- Bitcoin on-chain data (`btc.active_addresses`, `btc.nvt`, `btc.revenue_per_difficulty`) is
  computed from Bitcoin blocks, history included since 2013. `nvt_signal` is the day's market
  cap divided by the 90-day average of on-chain volume in USD; its `label` compares it with
  its own last 730 days.
