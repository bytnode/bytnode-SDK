"""Base class of every model returned by the SDK."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class BytnodeModel(BaseModel):
    """A row of the API.

    Attributes carry the API's own field names, so the documentation reads the same.
    A field the SDK does not know yet (added by the API after this release) is kept as an
    extra attribute: a newer API never breaks an older SDK.

    Also readable like a mapping: `row["close"]`, `row.get("venue_count")`.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True, protected_namespaces=(), defer_build=True)

    def __getitem__(self, key: str) -> Any:
        fields = type(self).model_fields
        if key in fields:
            return getattr(self, key)
        for name, info in fields.items():
            if info.alias == key:
                return getattr(self, name)
        extra = self.__pydantic_extra__ or {}
        if key in extra:
            return extra[key]
        raise KeyError(key)

    def __contains__(self, key: object) -> bool:
        try:
            self[key]  # type: ignore[index]
        except KeyError:
            return False
        return True

    def get(self, key: str, default: Any = None) -> Any:
        """The value of `key` (wire name or attribute), or `default`."""
        try:
            return self[key]
        except KeyError:
            return default

    def to_dict(self) -> dict[str, Any]:
        """The row as a plain dict, keyed by the API's field names."""
        return self.model_dump(by_alias=True, mode="python")
