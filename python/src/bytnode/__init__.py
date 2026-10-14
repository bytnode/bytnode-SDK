"""Official Python SDK of the BytNode crypto market-data API.

    from bytnode import Bytnode

    client = Bytnode()                         # reads BYTNODE_API_KEY
    candles = client.klines.history("BTCUSDT", "1h", limit=24)
    df = client.klines.history.iter("BTCUSDT", "1h", since="2026-01-01").to_pandas()

Docs: https://bytnode.com/docs · Reference: https://api.bytnode.com/openapi.json
"""

from . import channels, indicators, mcp, models, types
from ._client import AsyncBytnode, Bytnode
from ._errors import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    BytnodeError,
    ConnectionLimitError,
    InvalidRequestError,
    MissingAPIKeyError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServerError,
    StreamError,
)
from ._generated.routes import API_VERSION
from ._ratelimit import RateLimit
from ._response import AsyncRowIterator, BytnodeWarning, Response, RowIterator
from ._stream import (
    AsyncStream,
    BookMessage,
    LiquidationsMessage,
    StreamBook,
    StreamLiquidation,
    StreamMessage,
    StreamTrade,
    SyncStream,
    TradesMessage,
)
from ._types import RequestOptions
from ._version import __version__

__all__ = [
    "API_VERSION",
    "APIConnectionError",
    "APIError",
    "APITimeoutError",
    "AsyncBytnode",
    "AsyncRowIterator",
    "AsyncStream",
    "AuthenticationError",
    "BookMessage",
    "Bytnode",
    "BytnodeError",
    "BytnodeWarning",
    "ConnectionLimitError",
    "InvalidRequestError",
    "LiquidationsMessage",
    "MissingAPIKeyError",
    "NotFoundError",
    "PermissionDeniedError",
    "RateLimit",
    "RateLimitError",
    "RequestOptions",
    "Response",
    "RowIterator",
    "ServerError",
    "StreamBook",
    "StreamError",
    "StreamLiquidation",
    "StreamMessage",
    "StreamTrade",
    "SyncStream",
    "TradesMessage",
    "__version__",
    "channels",
    "indicators",
    "mcp",
    "models",
    "types",
]
