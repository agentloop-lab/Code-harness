"""Command-line entry point for Code Harness."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, TextIO

from agent.loop import AgentLoop, AgentLoopError
from agent.model import ModelClient, ModelClientError, ModelConfigError
from tools import ToolExecutor


SYSTEM_PROMPT = (
    "You are a coding agent working only inside the provided workspace. "
    "Use list_files instead of a shell command to inspect file paths. Use the "
    "available tools to inspect and modify files. Read an existing file "
    "before editing it, make focused changes, and run relevant checks before "
    f"finishing. Use this exact Python interpreter: {sys.executable}. Always "
    "include -B when running Python commands to avoid bytecode cache files. "
    "Do not use python3 or another Python executable. Briefly summarize the "
    "result in your final answer."
)


class ConsoleToolExecutor:
    """Run tools while showing concise progress in the terminal."""

    def __init__(self, executor: ToolExecutor, output: TextIO = sys.stdout) -> None:
        self.executor = executor
        self.output = output
        self.step = 0

    def __call__(
        self,
        name: str,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        self.step += 1
        detail = self._call_detail(arguments)
        suffix = f": {detail}" if detail else ""
        print(f"[{self.step}] TOOL  {name}{suffix}", file=self.output)

        result = self.executor(name, arguments)
        self._show_result(name, result)
        return result

    @staticmethod
    def _call_detail(arguments: Mapping[str, Any]) -> str:
        path = arguments.get("path")
        if isinstance(path, str):
            return path
        command = arguments.get("command")
        if isinstance(command, (list, tuple)):
            parts = [str(part) for part in command]
            if parts and parts[0].casefold() == sys.executable.casefold():
                parts[0] = "python"
            return " ".join(parts)
        return ""

    def _show_result(self, name: str, result: Mapping[str, Any]) -> None:
        success = result.get("success") is True
        marker = "OK" if success else "FAIL"
        content = result.get("content")

        command_details = None
        if name == "run_command" and isinstance(content, str):
            command_details = self._show_command_output(content)

        if command_details is not None:
            summary = f"Command exited with code {command_details.get('exit_code')}."
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
            summary = content.splitlines()[0][:300]
        else:
            summary = str(result.get("error_type") or "Tool completed.")
        print(f"    {marker:<5} {summary}", file=self.output)

    def _show_command_output(self, content: str) -> dict[str, Any] | None:
        try:
            details = json.loads(content)
        except json.JSONDecodeError:
            return None
        if not isinstance(details, dict):
            return None
        for stream_name, label in (("stdout", "OUT"), ("stderr", "ERR")):
            stream = details.get(stream_name)
            if isinstance(stream, str) and stream.strip():
                for line in stream.rstrip().splitlines():
                    print(f"    {label:<5} {line}", file=self.output)
        return details


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Code Harness agent.")
    parser.add_argument(
        "task",
        nargs="*",
        help="Task for the agent. If omitted, the CLI prompts for it.",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path("workspace"),
        help="Directory the agent may access (default: ./workspace).",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=10,
        help="Maximum number of model steps (default: 10).",
    )
    return parser


def _user_error_message(error: Exception) -> str:
    """Return the most useful safe message from a wrapped agent error."""

    current: BaseException | None = error
    while current is not None:
        if isinstance(current, ModelClientError):
            return str(current)
        current = current.__cause__
    return str(error)


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    input_fn: Callable[[str], str] = input,
    output: TextIO = sys.stdout,
) -> int:
    """Run one coding task from command-line arguments or a prompt."""

    args = _parser().parse_args(argv)
    task = " ".join(args.task).strip()
    if not task:
        task = input_fn("Task> ").strip()
    if not task:
        print("Error: task cannot be empty.", file=output)
        return 2

    workspace = args.workspace.resolve()
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        if not workspace.is_dir():
            raise OSError("workspace is not a directory")

        executor = ToolExecutor(workspace)
        visible_executor = ConsoleToolExecutor(executor, output)
        model_client = ModelClient()
        loop = AgentLoop(
            model_client,
            tools=executor.definitions,
            tool_executor=visible_executor,
            max_steps=args.max_steps,
        )

        print("Code Harness", file=output)
        print("=" * 60, file=output)
        print(f"Model:     {model_client.config.model_name}", file=output)
        print(f"Workspace: {workspace}", file=output)
        print(f"Task:      {task}", file=output)
        print("-" * 60, file=output)
        answer = loop.run(task, system_prompt=SYSTEM_PROMPT)
        print("-" * 60, file=output)
        print("Result", file=output)
        print(answer or "(No final response.)", file=output)
        print("=" * 60, file=output)
        return 0
    except (AgentLoopError, ModelClientError, ModelConfigError, OSError, ValueError) as exc:
        print(f"Error: {_user_error_message(exc)}", file=output)
        return 1


def main() -> None:
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
