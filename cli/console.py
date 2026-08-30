"""Terminal rendering for tool progress."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TextIO

from tools import ToolExecutor


@dataclass
class ConsoleSettings:
    verbose: bool = False


class ConsoleToolExecutor:
    """Run tools while showing concise progress in the terminal."""

    def __init__(
        self,
        executor: ToolExecutor,
        output: TextIO = sys.stdout,
        settings: ConsoleSettings | None = None,
    ) -> None:
        self.executor = executor
        self.output = output
        self.settings = settings or ConsoleSettings()
        self.step = 0

    def __call__(
        self,
        name: str,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        self.step += 1
        detail = self._call_detail(arguments)
        result = self.executor(name, arguments)
        self._show_result(name, detail, result)
        return result

    @classmethod
    def _call_detail(cls, arguments: Mapping[str, Any]) -> str:
        path = arguments.get("path")
        if isinstance(path, str):
            return cls._shorten(path)
        command = arguments.get("command")
        if isinstance(command, (list, tuple)):
            parts = [str(part) for part in command]
            if parts and parts[0].casefold() == sys.executable.casefold():
                parts[0] = "python"
            return cls._shorten(" ".join(parts))
        return ""

    def _show_result(
        self,
        name: str,
        detail: str,
        result: Mapping[str, Any],
    ) -> None:
        success = result.get("success") is True
        marker = "OK" if success else "FAIL"
        content = result.get("content")

        command_details = None
        if name == "run_command" and isinstance(content, str):
            command_details = self._command_details(content)

        if command_details is not None:
            summary = f"exit {command_details.get('exit_code')}"
            duration = command_details.get("duration")
            if isinstance(duration, (int, float)):
                summary += f" | {duration:.2f}s"
            if not success:
                error_line = self._last_output_line(command_details)
                if error_line:
                    summary += f" | {self._shorten(error_line, 160)}"
        elif name == "list_files" and success:
            if content == "No files found.":
                summary = content
            else:
                count = len(str(content).splitlines())
                summary = f"Listed {count} file(s)."
        elif name == "read_file" and success:
            summary = "File read."
        elif name == "search_text" and success:
            summary = "Search completed."
        elif isinstance(content, str) and content:
            summary = self._shorten(content.splitlines()[0], 200)
        else:
            summary = str(result.get("error_type") or "Tool completed.")

        detail_text = f" {detail}" if detail else ""
        print(
            f"[{self.step}] {marker:<5} {name}{detail_text} | {summary}",
            file=self.output,
        )
        if self.settings.verbose:
            self._show_verbose_output(name, content, command_details)

    @staticmethod
    def _command_details(content: str) -> dict[str, Any] | None:
        try:
            details = json.loads(content)
        except json.JSONDecodeError:
            return None
        if not isinstance(details, dict):
            return None
        return details

    def _show_verbose_output(
        self,
        name: str,
        content: Any,
        command_details: dict[str, Any] | None,
    ) -> None:
        if name != "run_command" or command_details is None:
            if isinstance(content, str) and content:
                for line in content.rstrip().splitlines():
                    print(f"    OUT   {line}", file=self.output)
            return

        for stream_name, label in (("stdout", "OUT"), ("stderr", "ERR")):
            stream = command_details.get(stream_name)
            if isinstance(stream, str) and stream.strip():
                for line in stream.rstrip().splitlines():
                    print(f"    {label:<5} {line}", file=self.output)

    @staticmethod
    def _last_output_line(details: Mapping[str, Any]) -> str:
        for stream_name in ("stderr", "stdout"):
            stream = details.get(stream_name)
            if isinstance(stream, str) and stream.strip():
                return stream.strip().splitlines()[-1]
        return ""

    @staticmethod
    def _shorten(text: str, max_chars: int = 120) -> str:
        compact = " ".join(text.split())
        if len(compact) <= max_chars:
            return compact
        return f"{compact[: max_chars - 3]}..."
