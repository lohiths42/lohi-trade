"""Shared base model with camelCase JSON serialization."""

from typing import Any
from pydantic import BaseModel, ConfigDict


def to_camel(name: str) -> str:
    """Convert snake_case to camelCase."""
    parts = name.split("_")
    return parts[0] + "".join(w.capitalize() for w in parts[1:])


class CamelModel(BaseModel):
    """Base model that serializes fields as camelCase in JSON responses."""
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    def model_dump(self, *, by_alias: bool = True, **kwargs: Any) -> dict[str, Any]:
        return super().model_dump(by_alias=by_alias, **kwargs)
