"""First steps: latest values, a typed error, your quota.

    export BYTNODE_API_KEY=cb_live_...
    python examples/quickstart.py
"""

from bytnode import Bytnode, InvalidRequestError

with Bytnode() as client:
    candles = client.klines("BTCUSDT", "1h", limit=3)
    for c in candles:
        print(f"{c.time:%Y-%m-%d %H:%M}  open {c.open:>10.2f}  close {c.close:>10.2f}  volume {c.volume_total:,.1f}")

    funding = client.funding.rate("BTCUSDT").data
    if funding is not None:
        print(f"funding {funding.rate_pct:.4f} % per 8 h ({funding.apr_pct:.2f} % a year)")

    try:
        client.klines("BTCUSD", "1h")
    except InvalidRequestError as e:
        print(f"refused: {e.code} on `{e.param}` -> {e.message[:60]}...")

    if client.last_rate_limit:
        print(f"quota left this month: {client.last_rate_limit.quota_remaining}")
