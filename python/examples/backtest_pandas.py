"""A month of hourly candles, funding and open interest in one DataFrame, then a toy signal.

    pip install "bytnode[pandas]"
    python examples/backtest_pandas.py
"""

from datetime import datetime, timedelta, timezone

from bytnode import Bytnode

since = datetime.now(timezone.utc) - timedelta(days=30)

with Bytnode() as client:
    candles = client.klines.history.iter("BTCUSDT", "1h", since=since).to_pandas()
    oi = client.oi.history.iter("BTCUSDT", "1h", since=since).to_pandas()
    funding = client.funding.rate.history.iter("BTCUSDT", since=since).to_pandas()

frame = candles[["close", "volume"]].join(oi.add_prefix("oi_"), how="left")
frame["funding_pct"] = funding["rate_pct"].reindex(frame.index, method="ffill")
frame["ret_24h"] = frame["close"].pct_change(24)
frame["signal"] = (frame["funding_pct"] < 0) & (frame["ret_24h"] < -0.03)

print(frame.tail())
print(f"{int(frame['signal'].sum())} hours flagged over {len(frame)}")
