"""Command-line entry point for Code Harness."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from agent.context import ContextError, ContextManager
from agent.loop import AgentLoop, AgentLoopError
from agent.model import ModelClient, ModelClientError, ModelConfigError
from agent.session import Session, SessionError, SessionStore
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
DEFAULT_SESSION_DIRECTORY = Path(".agent/sessions")
DEFAULT_RESULT_DIRECTORY = Path(".agent/results")
EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit"}


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
        if isinstance(current, (ContextError, ModelClientError)):
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
    initial_task = " ".join(args.task).strip()

    workspace = args.workspace.resolve()
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        if not workspace.is_dir():
            raise OSError("workspace is not a directory")

        model_client = ModelClient()
        session_store = SessionStore(DEFAULT_SESSION_DIRECTORY)
        context_manager = ContextManager(
            DEFAULT_RESULT_DIRECTORY,
            on_auto_compaction=lambda before, after: print(
                f"[context] Auto-compacted: {before:,} -> {after:,} characters.",
                file=output,
            ),
        )
        session = session_store.create()
        loop = _create_loop(
            model_client,
            workspace,
            args.max_steps,
            session,
            context_manager,
            output,
        )

        print("Code Harness", file=output)
        print("=" * 60, file=output)
        print(f"Model:     {model_client.config.model_name}", file=output)
        print(f"Workspace: {workspace}", file=output)
        print(f"Session:   {session.session_id}", file=output)
        print("-" * 60, file=output)

        if initial_task:
            return _run_turn(initial_task, loop, session, session_store, output)

        print("Commands: /resume  /compact  /exit", file=output)
        while True:
            try:
                task = input_fn("Task> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nSession saved.", file=output)
                return 0
            if task.casefold() in EXIT_COMMANDS:
                print("Session saved.", file=output)
                return 0
            if task.casefold() == "/resume":
                selected = _select_session(
                    session_store,
                    session.session_id,
                    input_fn,
                    output,
                )
                if selected is not None:
                    session = selected
                    loop = _create_loop(
                        model_client,
                        workspace,
                        args.max_steps,
                        session,
                        context_manager,
                        output,
                    )
                    print(
                        f"Resumed: {session.display_title} "
                        f"({session.turn_count} turns)",
                        file=output,
                    )
                continue
            if task.casefold() == "/compact":
                _compact_session(
                    context_manager,
                    model_client,
                    loop,
                    session,
                    session_store,
                    output,
                )
                continue
            if not task:
                continue
            _run_turn(task, loop, session, session_store, output)
    except (
        ModelClientError,
        ModelConfigError,
        OSError,
        SessionError,
        ValueError,
    ) as exc:
        print(f"Error: {_user_error_message(exc)}", file=output)
        return 1


def _create_loop(
    model_client: ModelClient,
    workspace: Path,
    max_steps: int,
    session: Session,
    context_manager: ContextManager,
    output: TextIO,
) -> AgentLoop:
    executor = ToolExecutor(workspace)
    return AgentLoop(
        model_client,
        tools=executor.definitions,
        tool_executor=ConsoleToolExecutor(executor, output),
        max_steps=max_steps,
        history=session.messages,
        context_manager=context_manager,
    )


def _select_session(
    store: SessionStore,
    current_session_id: str,
    input_fn: Callable[[str], str],
    output: TextIO,
) -> Session | None:
    sessions = [
        session
        for session in store.list_recent()
        if session.session_id != current_session_id
    ]
    if not sessions:
        print("No other saved sessions.", file=output)
        return None

    print("Recent sessions", file=output)
    for index, session in enumerate(sessions, start=1):
        updated = datetime.fromisoformat(session.updated_at).astimezone()
        print(
            f"  {index}. {session.display_title}\n"
            f"     {updated:%m-%d %H:%M} · {session.turn_count} turns",
            file=output,
        )
    print("Press Enter to cancel.", file=output)

    while True:
        try:
            choice = input_fn("Resume> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nResume cancelled.", file=output)
            return None
        if not choice:
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(sessions):
            return sessions[int(choice) - 1]
        print("Choose a session number from the list.", file=output)


def _compact_session(
    context_manager: ContextManager,
    model_client: ModelClient,
    loop: AgentLoop,
    session: Session,
    session_store: SessionStore,
    output: TextIO,
) -> None:
    if session.turn_count == 0:
        print("Nothing to compact yet.", file=output)
        return

    if not session.title:
        session.title = session.display_title
    before = context_manager.estimate_size(loop.messages)
    try:
        compacted = context_manager.compact_history(loop.messages, model_client)
    except (ContextError, ModelClientError) as exc:
        print(f"Error: {exc}", file=output)
        return

    after = context_manager.estimate_size(compacted)
    if after >= before:
        print(f"Context is already compact ({before:,} characters).", file=output)
        return

    loop.messages = compacted
    session.messages = compacted
    session_store.save(session)
    print(f"Compacted context: {before:,} -> {after:,} characters.", file=output)


def _run_turn(
    task: str,
    loop: AgentLoop,
    session: Session,
    session_store: SessionStore,
    output: TextIO,
) -> int:
    """Run and save one turn of a conversation."""

    print(f"You: {task}", file=output)
    try:
        answer = loop.run(task, system_prompt=SYSTEM_PROMPT)
    except AgentLoopError as exc:
        session.messages = loop.messages
        session.total_turns += 1
        session_store.save(session)
        print(f"Error: {_user_error_message(exc)}", file=output)
        return 1

    session.messages = loop.messages
    session.total_turns += 1
    session_store.save(session)
    print("Agent:", file=output)
    print(answer or "(No final response.)", file=output)
    print("-" * 60, file=output)
    return 0


def main() -> None:
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
