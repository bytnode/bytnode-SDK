"""Turn the time bounds people actually write into the epoch milliseconds the API wants."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
# 1e11 ms = 1973-03-03: anything below is a timestamp in SECONDS (or a mistake).
_SECONDS_CEILING = 100_000_000_000

TIME_PARAMS = frozenset({"since_ms", "until_ms", "before_ms"})

# Duration of each timeframe, to rebuild candle times (indicators) and step pages.
TIMEFRAME_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
    "1w": 604_800_000,
}


def to_ms(value: object, name: str = "time") -> int:
    """Epoch milliseconds for a `datetime`, `date`, ISO string or millisecond integer.

    A naive `datetime` is read as UTC. An integer that looks like SECONDS is refused rather
    than silently read as 1970: the API would refuse it too, with a less direct message.
    """
    if isinstance(value, bool):
        raise TypeError(f"{name}: expected a datetime, a date, an ISO string or epoch milliseconds, got a bool")
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return (dt - _EPOCH) // timedelta(milliseconds=1)
    if isinstance(value, date):
        return to_ms(datetime(value.year, value.month, value.day, tzinfo=timezone.utc), name)
    if isinstance(value, (int, float)):
        ms = int(value)
        if abs(ms) < _SECONDS_CEILING:
            raise ValueError(
                f"{name}={value!r} looks like a timestamp in seconds: pass epoch milliseconds "
                f"({ms * 1000}), a datetime or an ISO string"
            )
        return ms
    if isinstance(value, str):
        text = value.strip()
        if text.lstrip("-").isdigit():
            return to_ms(int(text), name)
        try:
            if len(text) == 10:
                return to_ms(date.fromisoformat(text), name)
            return to_ms(datetime.fromisoformat(text.replace("Z", "+00:00").replace("z", "+00:00")), name)
        except ValueError:
            raise ValueError(
                f"{name}={value!r} is not a date: use an ISO string ('2026-01-01', '2026-01-01T12:00:00Z'), "
                "a datetime or epoch milliseconds"
            ) from None
    # pandas.Timestamp is a datetime; numpy.datetime64 and friends expose isoformat()
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        return to_ms(str(iso()), name)
    raise TypeError(
        f"{name}: expected a datetime, a date, an ISO string or epoch milliseconds, got {type(value).__name__}"
    )


def from_ms(ms: int) -> datetime:
    """The UTC `datetime` of epoch milliseconds."""
    return _EPOCH + timedelta(milliseconds=ms)
