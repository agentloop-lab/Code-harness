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
    LIST_FILES_DEFINITION,
    READ_FILE_DEFINITION,
    SEARCH_TEXT_DEFINITION,
    WRITE_FILE_DEFINITION,
    edit_file,
    list_files,
    read_file,
    read_file_snapshot,
    search_text,
    write_file,
)
from tools.paths import WorkspacePathError, resolve_workspace_path


class ToolExecutor:
    """Execute the tools available for one workspace."""

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).resolve()
        self._file_versions: dict[Path, str] = {}

    @property
    def definitions(self) -> list[dict[str, Any]]:
        return [
            LIST_FILES_DEFINITION,
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

        call_arguments = dict(arguments)
        target = self._argument_path(call_arguments)
        if name == "edit_file":
            if "expected_version" in call_arguments:
                return ToolResult(
                    False,
                    "Invalid arguments for tool: edit_file",
                    "InvalidArguments",
                ).to_dict()
            call_arguments["expected_version"] = self._file_versions.get(target)

        try:
            bound_arguments = inspect.signature(handler).bind(
                self.workspace,
                **call_arguments,
            )
        except TypeError:
            return ToolResult(
                False,
                f"Invalid arguments for tool: {name}",
                "InvalidArguments",
            ).to_dict()

        try:
            if name == "read_file":
                result, version = read_file_snapshot(
                    *bound_arguments.args,
                    **bound_arguments.kwargs,
                )
            else:
                result = handler(*bound_arguments.args, **bound_arguments.kwargs)
                version = None
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

        if name == "read_file" and target is not None:
            if result.success and version is not None:
                self._file_versions[target] = version
            else:
                self._file_versions.pop(target, None)
        elif name == "edit_file" and target is not None:
            if result.success or result.error_type == "StaleFile":
                self._file_versions.pop(target, None)
        return result.to_dict()

    def _argument_path(self, arguments: Mapping[str, Any]) -> Path | None:
        path = arguments.get("path")
        if not isinstance(path, str) or not path:
            return None
        try:
            return resolve_workspace_path(self.workspace, path)
        except WorkspacePathError:
            return None

    @staticmethod
    def _handlers() -> dict[str, Any]:
        return {
            "list_files": list_files,
            "read_file": read_file,
            "search_text": search_text,
            "write_file": write_file,
            "edit_file": edit_file,
            "run_command": run_command,
        }
