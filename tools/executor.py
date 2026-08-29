"""Dispatch local tool calls."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tools.base import ToolResult
from tools.command_tools import RUN_COMMAND_DEFINITION, run_command
from tools.file_tools import (
    EDIT_FILE_DEFINITION,
    READ_FILE_DEFINITION,
    SEARCH_TEXT_DEFINITION,
    WRITE_FILE_DEFINITION,
    edit_file,
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
            EDIT_FILE_DEFINITION,
            RUN_COMMAND_DEFINITION,
        ]

    def __call__(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        handler = self._handlers().get(name)
        if handler is None:
            return ToolResult(False, f"Unknown tool: {name}", "UnknownTool").to_dict()
        if not isinstance(arguments, Mapping):
            return ToolResult(
                False,
                f"Invalid arguments for tool: {name}",
                "InvalidArguments",
            ).to_dict()

        try:
            bound_arguments = inspect.signature(handler).bind(
                self.workspace,
                **dict(arguments),
            )
        except TypeError:
            return ToolResult(
                False,
                f"Invalid arguments for tool: {name}",
                "InvalidArguments",
            ).to_dict()

        try:
            result = handler(*bound_arguments.args, **bound_arguments.kwargs)
        except Exception:
            return ToolResult(
                False,
                f"Tool execution failed: {name}",
                "ToolError",
            ).to_dict()

        if not isinstance(result, ToolResult):
            return ToolResult(
                False,
                f"Tool returned an invalid result: {name}",
                "ToolError",
            ).to_dict()
        return result.to_dict()

    @staticmethod
    def _handlers() -> dict[str, Any]:
        return {
            "read_file": read_file,
            "search_text": search_text,
            "write_file": write_file,
            "edit_file": edit_file,
            "run_command": run_command,
        }
