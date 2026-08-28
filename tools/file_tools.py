"""Read-only file tools."""

from __future__ import annotations

from pathlib import Path

from tools.base import ToolResult


DEFAULT_MAX_CHARS = 20_000
TRUNCATION_MARKER = "\n...[truncated]"

READ_FILE_DEFINITION = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read a UTF-8 text file inside the workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "minimum": 1},
                "end_line": {"type": "integer", "minimum": 1},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
}


def read_file(
    workspace: str | Path,
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> ToolResult:
    """Read all or part of a UTF-8 file within a workspace."""

    if not isinstance(path, str) or not path:
        return ToolResult(False, "path must be a non-empty string.", "InvalidArguments")
    if not _valid_line_range(start_line, end_line):
        return ToolResult(False, "Invalid line range.", "InvalidArguments")
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars < 1:
        return ToolResult(False, "max_chars must be a positive integer.", "InvalidArguments")

    root = Path(workspace).resolve()
    requested = Path(path)
    target = requested.resolve() if requested.is_absolute() else (root / requested).resolve()

    try:
        target.relative_to(root)
    except ValueError:
        return ToolResult(False, "Path is outside the workspace.", "PathOutsideWorkspace")

    if not target.exists():
        return ToolResult(False, f"File does not exist: {path}", "FileNotFound")
    if not target.is_file():
        return ToolResult(False, f"Path is not a file: {path}", "NotAFile")

    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ToolResult(False, f"File is not valid UTF-8: {path}", "DecodeError")
    except OSError:
        return ToolResult(False, f"Could not read file: {path}", "ReadError")

    if start_line is not None or end_line is not None:
        lines = content.splitlines(keepends=True)
        first = (start_line or 1) - 1
        last = end_line
        content = "".join(lines[first:last])

    if len(content) > max_chars:
        if max_chars >= len(TRUNCATION_MARKER):
            content = content[: max_chars - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER
        else:
            content = content[:max_chars]

    return ToolResult(True, content)


def _valid_line_range(start_line: int | None, end_line: int | None) -> bool:
    values = (start_line, end_line)
    if any(
        value is not None
        and (not isinstance(value, int) or isinstance(value, bool) or value < 1)
        for value in values
    ):
        return False
    return start_line is None or end_line is None or start_line <= end_line
