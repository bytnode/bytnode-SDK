"""Typed builders for `client.indicators(...)`: parameters checked locally, ids generated.

from bytnode import indicators as ind

res = client.indicators("BTCUSDT", "1h", [ind.rsi(14), ind.macd(), ind.bb(20, std=2.5)], results=100)
res.data.indicators["rsi_14"].values
res.to_pandas()      # one column per output (`macd_12_26_9.signal`...), indexed by candle time
"""

from ._generated.indicators import *  # noqa: F403
from ._generated.indicators import __all__ as _generated
from ._indicator_spec import IndicatorSpec

__all__ = [*_generated, "IndicatorSpec"]
