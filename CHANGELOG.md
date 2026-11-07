# Changelog

All notable changes to the BytNode SDKs. Both packages share one version number.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

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
