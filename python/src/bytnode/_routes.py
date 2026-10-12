"""What the runtime needs to know about a route (filled in by the generated code)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RouteSpec:
    path: str
    method: str
    shape: str  # "object" | "list" | "scalar" | "snapshot" | "indicators"
    model: Any  # the row model class, or None
    paginated: bool
    path_params: tuple[str, ...] = ()
    max_limit: int | None = None
    range_mode: bool = False  # ticks: `next` only exists in range reading
