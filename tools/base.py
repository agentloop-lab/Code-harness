"""Shared types for local tools."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ToolResult:
    """Result returned by a local tool."""

    success: bool
    content: str
    error_type: str | None = None

    def to_dict(self) -> dict[str, bool | str | None]:
        return asdict(self)
