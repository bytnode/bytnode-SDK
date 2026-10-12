"""Real-time trades and order book, with loss detection. Ctrl+C to stop.

    python examples/stream_trades.py
"""

from bytnode import Bytnode, BookMessage
from bytnode import channels as ch

with Bytnode() as client, client.stream(ch.trades("BTCUSDT"), ch.book("BTCUSDT"), depth=3) as stream:
    print("subscribed to", stream.channels)
    for msg in stream:
        if msg.gap:
            print(f"!! {msg.gap} message(s) lost on {msg.channel}")
        if isinstance(msg, BookMessage):
            book = msg.data
            print(f"book  mid {book.mid_avg:.2f}  spread {book.avg_spread_bps:.3f} bps  best bid {book.bids[0]}")
        else:
            notional = sum(t.price * t.quantity for t in msg.data)
            print(f"{msg.kind:<6} {len(msg.data):>3} prints, {notional:,.0f} USD")
