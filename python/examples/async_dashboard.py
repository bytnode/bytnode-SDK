"""Many symbols at once with the asyncio client.

    python examples/async_dashboard.py
"""

import asyncio

from bytnode import AsyncBytnode

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]


async def main() -> None:
    async with AsyncBytnode() as client:
        funding = await asyncio.gather(*(client.funding.rate(s) for s in SYMBOLS))
        basis = await asyncio.gather(*(client.basis(s) for s in SYMBOLS))
        for symbol, f, b in zip(SYMBOLS, funding, basis, strict=True):
            rate = f"{f.data.rate_pct:+.4f} %" if f.data else "n/a"
            spread = f"{b.data.basis_pct:+.3f} %" if b.data else "n/a"
            print(f"{symbol:<8} funding {rate:>10}   basis {spread:>8}")


asyncio.run(main())
