"""Types shared by the public signatures."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import TypedDict, Union

TimeLike = Union[datetime, date, str, int]
"""A point in time: a `datetime` (naive = UTC), a `date` (midnight UTC), an ISO string
(`2026-01-01`, `2026-01-01T12:00:00Z`) or epoch MILLISECONDS."""

Fields = Union[str, Sequence[str]]
"""Fields to keep in each row: a list, or a comma-separated string (`"time,close"`)."""

Depth = Union[bool, int]
"""A snapshot depth: `True` for the latest value, `N` for the N latest rows."""


class RequestOptions(TypedDict, total=False):
    """Per-request overrides."""

    timeout: float
    """Seconds before giving up on one attempt."""
    max_retries: int
    """Automatic retries on rate limits, 502/503/504 and network errors."""
    headers: Mapping[str, str]
    """Extra HTTP headers."""
