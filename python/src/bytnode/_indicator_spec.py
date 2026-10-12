"""The indicator spec sent to `POST /v1/indicators`, and its local checks."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

_ID = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")


@dataclass(frozen=True)
class IndicatorSpec:
    """One indicator to compute: its `type`, its parameters and the `id` of its result."""

    type: str
    params: dict[str, Any] = field(default_factory=dict)
    id: str | None = None

    def default_id(self) -> str:
        values = "_".join(_fmt(v) for v in self.params.values())
        return f"{self.type}_{values}" if values else self.type


def _fmt(v: Any) -> str:
    # the same ids as the TypeScript SDK: 2.0 -> "2", 2.5 -> "2p5"
    text = str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)
    return text.replace(".", "p").replace("-", "m")


def _check(kind: str, name: str, value: Any, minimum: float, maximum: float | None, integer: bool) -> Any:
    """Refuse locally what the API would refuse with a 422 — sooner and clearer."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{kind}.{name} must be a number, got {value!r}")
    if integer and not float(value).is_integer():
        raise ValueError(f"{kind}.{name} must be an integer, got {value!r}")
    if value < minimum or (maximum is not None and value > maximum):
        bound = f">= {minimum}" if maximum is None else f"between {minimum} and {maximum}"
        raise ValueError(f"{kind}.{name} must be {bound}, got {value!r}")
    return int(value) if integer else float(value)


def indicators_body(indicators: Sequence[IndicatorSpec | Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The `indicators` list of the request: ids filled in, unique."""
    if not indicators:
        raise ValueError("indicators: give at least one indicator, e.g. bytnode.indicators.rsi(14)")
    if len(indicators) > 50:
        raise ValueError(f"indicators: at most 50 per call, got {len(indicators)}")
    out: list[dict[str, Any]] = []
    used: set[str] = set()
    for spec in indicators:
        if isinstance(spec, IndicatorSpec):
            item: dict[str, Any] = {"type": spec.type, **spec.params}
            ident = spec.id or spec.default_id()
        elif isinstance(spec, Mapping):
            item = dict(spec)
            if "type" not in item:
                raise ValueError(f"indicators: missing 'type' in {spec!r}")
            params = {k: v for k, v in item.items() if k not in ("id", "type")}
            ident = item.pop("id", None) or IndicatorSpec(item["type"], params).default_id()
        else:
            raise TypeError(f"indicators: expected bytnode.indicators.<type>(...) or a dict, got {type(spec).__name__}")
        if not _ID.match(ident):
            raise ValueError(f"indicators: invalid id {ident!r} (1 to 64 letters, digits, '_', '-', '.')")
        base, n = ident, 2
        while ident in used:  # the same indicator twice: keep both
            ident = f"{base}_{n}"
            n += 1
        used.add(ident)
        out.append({"id": ident, **item})
    return out
