"""Local command execution tool."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Sequence

from tools.base import ToolResult


DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_OUTPUT_CHARS = 20_000
TRUNCATION_MARKER = "\n...[truncated]"

RUN_COMMAND_DEFINITION = {
    "type": "function",
    "function": {
        "name": "run_command",
        "description": "Run a command in the workspace without using a shell.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
                "timeout": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "default": DEFAULT_TIMEOUT,
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
}


def run_command(
    workspace: str | Path,
    command: Sequence[str],
    timeout: float = DEFAULT_TIMEOUT,
    max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
) -> ToolResult:
    """Run a command with a fixed workspace and bounded output."""

    if not _valid_command(command):
        return ToolResult(
            False,
            "command must be a non-empty list of strings.",
            "InvalidArguments",
        )
    if (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or timeout <= 0
    ):
        return ToolResult(False, "timeout must be positive.", "InvalidArguments")
    if (
        not isinstance(max_output_chars, int)
        or isinstance(max_output_chars, bool)
        or max_output_chars < 1
    ):
        return ToolResult(
            False,
            "max_output_chars must be a positive integer.",
            "InvalidArguments",
        )

    root = Path(workspace).resolve()
    if not root.is_dir():
        return ToolResult(False, "Workspace does not exist.", "WorkspaceNotFound")

    command_list = list(command)
    started_at = time.perf_counter()
    try:
        completed = subprocess.run(
            command_list,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.perf_counter() - started_at
        content = _result_content(
            command_list,
            None,
            _as_text(exc.stdout),
            _as_text(exc.stderr),
            duration,
            max_output_chars,
        )
        return ToolResult(False, content, "CommandTimeout")
    except FileNotFoundError:
        duration = time.perf_counter() - started_at
        content = _result_content(
            command_list,
            None,
            "",
            f"Command not found: {command_list[0]}",
            duration,
            max_output_chars,
        )
        return ToolResult(False, content, "CommandNotFound")
    except OSError:
        duration = time.perf_counter() - started_at
        content = _result_content(
            command_list,
            None,
            "",
            "Could not run command.",
            duration,
            max_output_chars,
        )
        return ToolResult(False, content, "CommandError")

    duration = time.perf_counter() - started_at
    content = _result_content(
        command_list,
        completed.returncode,
        completed.stdout,
        completed.stderr,
        duration,
        max_output_chars,
    )
    if completed.returncode != 0:
        return ToolResult(False, content, "CommandFailed")
    return ToolResult(True, content)


def _valid_command(command: Sequence[str]) -> bool:
    return (
        isinstance(command, (list, tuple))
        and bool(command)
        and all(isinstance(part, str) and part for part in command)
    )


def _result_content(
    command: list[str],
    exit_code: int | None,
    stdout: str,
    stderr: str,
    duration: float,
    max_output_chars: int,
) -> str:
    result: dict[str, Any] = {
        "command": command,
        "exit_code": exit_code,
        "stdout": _truncate(stdout, max_output_chars),
        "stderr": _truncate(stderr, max_output_chars),
        "duration": round(duration, 3),
    }
    return json.dumps(result, ensure_ascii=False)


def _truncate(content: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    if max_chars < len(TRUNCATION_MARKER):
        return content[:max_chars]
    return content[: max_chars - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER


def _as_text(content: str | bytes | None) -> str:
    if content is None:
        return ""
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    return content
