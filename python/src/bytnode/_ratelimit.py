"""Read the IETF `RateLimit` / `RateLimit-Policy` headers of a response."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

# The API names its two policies "rate" (rate limit) and "quota" (monthly quota).
_RATE_NAMES = {"rate", "burst", "rate_limit"}
_QUOTA_NAMES = {"monthly", "quota", "month"}


def parse_policies(header: str | None) -> dict[str, dict[str, int]]:
    """`"rate";q=600;w=60, "quota";q=100000;w=2592000` -> {"rate": {"q": 600, "w": 60}, ...}."""
    out: dict[str, dict[str, int]] = {}
    if not header:
        return out
    for part in header.split(","):
        pieces = [p.strip() for p in part.split(";")]
        name = pieces[0].strip('"').strip()
        if not name:
            continue
        params: dict[str, int] = {}
        for kv in pieces[1:]:
            if "=" in kv:
                k, v = kv.split("=", 1)
                try:
                    params[k.strip()] = int(float(v.strip().strip('"')))
                except ValueError:
                    continue
        out[name] = params
    return out


@dataclass(frozen=True)
class RateLimit:
    """Where you stand against your plan, as announced by the last response.

    `limit` / `remaining` / `reset_s` describe the rate limit (requests per window),
    `quota_*` the monthly quota. A field is `None` when the API did not send it (keys that
    are not metered carry no headers).
    """

    limit: int | None = None
    remaining: int | None = None
    reset_s: int | None = None
    window_s: int | None = None
    quota_limit: int | None = None
    quota_remaining: int | None = None
    quota_reset_s: int | None = None
    quota_window_s: int | None = None
    policies: dict[str, dict[str, int]] = field(default_factory=dict)

    @classmethod
    def from_headers(cls, headers: Mapping[str, str]) -> RateLimit | None:
        policy = parse_policies(headers.get("ratelimit-policy"))
        state = parse_policies(headers.get("ratelimit"))
        if not policy and not state:
            return None
        names = list(dict.fromkeys([*policy, *state]))

        def pick(known: set[str], largest: bool) -> str | None:
            for n in names:
                if n.lower() in known:
                    return n
            windows = [(policy.get(n, {}).get("w", 0), n) for n in names]
            return (max if largest else min)(windows)[1] if windows else None

        rate, quota = pick(_RATE_NAMES, False), pick(_QUOTA_NAMES, True)
        if rate == quota:
            quota = None

        def get(name: str | None, src: dict[str, dict[str, int]], key: str) -> int | None:
            return src.get(name, {}).get(key) if name else None

        return cls(
            limit=get(rate, policy, "q"),
            remaining=get(rate, state, "r"),
            reset_s=get(rate, state, "t"),
            window_s=get(rate, policy, "w"),
            quota_limit=get(quota, policy, "q"),
            quota_remaining=get(quota, state, "r"),
            quota_reset_s=get(quota, state, "t"),
            quota_window_s=get(quota, policy, "w"),
            policies={n: {**policy.get(n, {}), **state.get(n, {})} for n in names},
        )
