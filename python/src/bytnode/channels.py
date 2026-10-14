"""Names of the WebSocket channels, without typos.

from bytnode import channels as ch

with client.stream(ch.trades("BTCUSDT"), ch.orderbook("ETHUSDT", market="spot")) as stream:
    ...
"""

from __future__ import annotations

from typing import Literal

StreamMarket = Literal["futures", "spot"]


def trades(symbol: str, market: StreamMarket = "futures") -> str:
    """Every execution of `symbol`, pushed in 100 ms packets: `trades.<market>.<SYMBOL>`."""
    return f"trades.{_market(market)}.{symbol.upper()}"


def orderbook(symbol: str, market: StreamMarket = "futures") -> str:
    """The consolidated order book of `symbol`, every 100 ms: `orderbook.<market>.<SYMBOL>`."""
    return f"orderbook.{_market(market)}.{symbol.upper()}"


# Kept as an alias of `orderbook` (the channel was named `book.*` before contract 3.0.0).
book = orderbook


def liquidations(symbol: str) -> str:
    """The liquidations of `symbol` (perpetual futures): `liquidations.<SYMBOL>`."""
    return f"liquidations.{symbol.upper()}"


def _market(market: str) -> str:
    if market not in ("futures", "spot"):
        raise ValueError(f"market must be 'futures' or 'spot', got {market!r}")
    return market


__all__ = ["StreamMarket", "book", "liquidations", "orderbook", "trades"]
