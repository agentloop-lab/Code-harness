"""Dispatch local tool calls."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from tools.base import ToolResult
from tools.file_tools import (
    READ_FILE_DEFINITION,
    SEARCH_TEXT_DEFINITION,
    WRITE_FILE_DEFINITION,
    read_file,
    search_text,
    write_file,
)


class ToolExecutor:
    """Execute the tools available for one workspace."""

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).resolve()

    @property
    def definitions(self) -> list[dict[str, Any]]:
        return [
            READ_FILE_DEFINITION,
            SEARCH_TEXT_DEFINITION,
            WRITE_FILE_DEFINITION,
        ]

    def __call__(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if name == "read_file":
            result = read_file(self.workspace, **arguments)
        elif name == "search_text":
            result = search_text(self.workspace, **arguments)
        elif name == "write_file":
            result = write_file(self.workspace, **arguments)
        else:
            result = ToolResult(False, f"Unknown tool: {name}", "UnknownTool")
        return result.to_dict()
