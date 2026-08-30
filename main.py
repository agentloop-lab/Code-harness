"""Command-line entry point for Code Harness."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import (
    CompleteEvent,
    Completer,
    Completion,
    PathCompleter,
)
from prompt_toolkit.document import Document
from prompt_toolkit.history import FileHistory
from prompt_toolkit.input import Input
from prompt_toolkit.output import Output
from prompt_toolkit.shortcuts import CompleteStyle

from agent.context import ContextError, ContextManager
from agent.loop import AgentLoop, AgentLoopError
from agent.memory import ProjectMemoryStore
from agent.model import ModelClient, ModelClientError, ModelConfigError
from agent.session import Session, SessionError, SessionStore
from agent.workspace import WorkspaceTracker
from tools import ToolExecutor, read_file


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
DEFAULT_MEMORY_FILE = Path(".agent/memory.md")
DEFAULT_PROJECT_DIRECTORY = Path(".agent/projects")
DEFAULT_HISTORY_FILE = Path(".agent/history")
EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit"}
FILE_REFERENCE_PATTERN = re.compile(r"(?<!\S)@([^\s]+)")
MAX_REFERENCE_FILES = 5
MAX_REFERENCE_CHARS = 30_000
MAX_REFERENCE_FILE_CHARS = 6_000


@dataclass(frozen=True)
class SlashCommand:
    name: str
    usage: str
    description: str


SLASH_COMMANDS = (
    SlashCommand("/workspace", "/workspace", "Show current workspace"),
    SlashCommand("/open", "/open <path>", "Switch workspace"),
    SlashCommand("/resume", "/resume", "Resume a saved session"),
    SlashCommand("/compact", "/compact", "Compact conversation context"),
    SlashCommand("/memory", "/memory", "Show project memory"),
    SlashCommand("/remember", "/remember <note>", "Save a project note"),
    SlashCommand("/verbose", "/verbose", "Toggle full tool output"),
    SlashCommand("/status", "/status", "Show latest workspace changes"),
    SlashCommand("/diff", "/diff", "Show latest code changes"),
    SlashCommand("/help", "/help", "Show available commands"),
    SlashCommand("/exit", "/exit", "Save the session and exit"),
)


class SlashCommandCompleter(Completer):
    """Complete slash commands at the start of a task prompt."""

    def __init__(
        self,
        workspace_getter: Callable[[], Path] | None = None,
    ) -> None:
        self._workspace_getter = workspace_getter
        self._path_completer = PathCompleter(
            only_directories=True,
            expanduser=True,
        )
        self._file_completer = PathCompleter(
            get_paths=lambda: (
                [str(self._workspace_getter())]
                if self._workspace_getter is not None
                else []
            ),
        )

    def get_completions(
        self,
        document: Document,
        _complete_event: CompleteEvent,
    ) -> Iterator[Completion]:
        text = document.text_before_cursor
        if text.casefold().startswith("/open "):
            path_text = text[len("/open ") :]
            yield from self._path_completer.get_completions(
                Document(path_text, cursor_position=len(path_text)),
                _complete_event,
            )
            return

        reference = re.search(r"(?:^|\s)@([^\s]*)$", text)
        if reference is not None and self._workspace_getter is not None:
            path_text = reference.group(1)
            yield from self._file_completer.get_completions(
                Document(path_text, cursor_position=len(path_text)),
                _complete_event,
            )
            return

        prefix = text.strip()
        if not prefix.startswith("/") or " " in prefix:
            return
        for command in SLASH_COMMANDS:
            if command.name.startswith(prefix.casefold()):
                yield Completion(
                    command.name,
                    start_position=-len(prefix),
                    display_meta=command.description,
                )


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


def _interactive_input(
    input_fn: Callable[[str], str],
    workspace_getter: Callable[[], Path] | None = None,
) -> Callable[[str], str]:
    if input_fn is not input or not sys.stdin.isatty():
        return input_fn

    task_session = _task_prompt_session(
        DEFAULT_HISTORY_FILE,
        workspace_getter=workspace_getter,
    )
    choice_session: PromptSession[str] = PromptSession()

    def read(prompt: str) -> str:
        session = task_session if prompt == "Task> " else choice_session
        return session.prompt(prompt)

    return read


def _task_prompt_session(
    history_file: Path,
    *,
    workspace_getter: Callable[[], Path] | None = None,
    prompt_input: Input | None = None,
    prompt_output: Output | None = None,
) -> PromptSession[str]:
    history_file.parent.mkdir(parents=True, exist_ok=True)
    session: PromptSession[str]
    session = PromptSession(
        history=FileHistory(str(history_file)),
        completer=SlashCommandCompleter(workspace_getter),
        complete_while_typing=True,
        complete_style=CompleteStyle.MULTI_COLUMN,
        input=prompt_input,
        output=prompt_output,
    )
    return session


def _user_error_message(error: Exception) -> str:
    """Return the most useful safe message from a wrapped agent error."""

    current: BaseException | None = error
    while current is not None:
        if isinstance(current, (ContextError, ModelClientError)):
            return str(current)
        current = current.__cause__
    return str(error)


def _memory_file_for_workspace(workspace: Path) -> Path:
    resolved = workspace.resolve()
    if resolved == Path("workspace").resolve():
        return DEFAULT_MEMORY_FILE
    key = hashlib.sha256(
        str(resolved).casefold().encode("utf-8")
    ).hexdigest()[:16]
    return DEFAULT_PROJECT_DIRECTORY / key / "memory.md"


def _attach_file_references(task: str, workspace: Path) -> tuple[str, list[str]]:
    references = list(dict.fromkeys(FILE_REFERENCE_PATTERN.findall(task)))
    if not references:
        return task, []
    if len(references) > MAX_REFERENCE_FILES:
        raise ValueError(
            f"A task can reference at most {MAX_REFERENCE_FILES} files."
        )

    sections = []
    remaining = MAX_REFERENCE_CHARS
    for path in references:
        result = read_file(
            workspace,
            path,
            max_chars=min(MAX_REFERENCE_FILE_CHARS, remaining),
        )
        if not result.success:
            raise ValueError(f"Could not attach @{path}: {result.content}")
        sections.append(f"[Referenced file: {path}]\n{result.content}")
        remaining -= len(result.content)
        if remaining <= 0:
            break

    attached = "\n\n".join(sections)
    prompt = (
        f"{task}\n\n"
        "The user explicitly referenced these workspace file snapshots. "
        "Use them as context. Read a file with the tool before editing it.\n\n"
        f"{attached}"
    )
    return prompt, references[: len(sections)]


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
        memory_store = ProjectMemoryStore(_memory_file_for_workspace(workspace))
        console_settings = ConsoleSettings()
        workspace_tracker = WorkspaceTracker(workspace)
        context_manager = ContextManager(
            DEFAULT_RESULT_DIRECTORY,
            on_auto_compaction=lambda before, after: print(
                f"[context] Auto-compacted: {before:,} -> {after:,} characters.",
                file=output,
            ),
        )
        session = session_store.create(workspace)
        loop = _create_loop(
            model_client,
            workspace,
            args.max_steps,
            session,
            context_manager,
            output,
            console_settings,
        )

        print(f"Code Harness | {model_client.config.model_name}", file=output)
        print(f"Workspace: {workspace}", file=output)
        print(f"Session:   {session.session_id}", file=output)

        if initial_task:
            agent_task, references = _attach_file_references(
                initial_task,
                workspace,
            )
            if references:
                print(
                    f"[context] Attached {len(references)} file(s).",
                    file=output,
                )
            workspace_tracker.start()
            print(f"Task> {initial_task}", file=output)
            return _run_turn(
                agent_task,
                loop,
                session,
                session_store,
                output,
                _system_prompt(memory_store.items()),
            )

        read_input = _interactive_input(input_fn, lambda: workspace)
        print("Commands: type / for help and completion", file=output)
        while True:
            try:
                task = read_input("Task> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nSession saved.", file=output)
                return 0
            if task.casefold() in EXIT_COMMANDS:
                print("Session saved.", file=output)
                return 0
            if task.casefold() == "/workspace":
                print(f"Workspace: {workspace}", file=output)
                continue
            if task.casefold() == "/open" or task.casefold().startswith(
                "/open "
            ):
                path_text = task[len("/open") :].strip()
                if not path_text:
                    print("Usage: /open <path>", file=output)
                    continue
                target = Path(path_text).expanduser().resolve()
                if not target.exists():
                    print(f"Workspace does not exist: {target}", file=output)
                    continue
                if not target.is_dir():
                    print(f"Workspace is not a directory: {target}", file=output)
                    continue
                if session.messages:
                    session.messages = loop.messages
                    session_store.save(session)
                workspace = target
                memory_store = ProjectMemoryStore(
                    _memory_file_for_workspace(workspace)
                )
                workspace_tracker = WorkspaceTracker(workspace)
                session = session_store.create(workspace)
                loop = _create_loop(
                    model_client,
                    workspace,
                    args.max_steps,
                    session,
                    context_manager,
                    output,
                    console_settings,
                )
                print(f"Workspace: {workspace}", file=output)
                print(f"Session:   {session.session_id}", file=output)
                continue
            if task.casefold() == "/resume":
                selected = _select_session(
                    session_store,
                    session.session_id,
                    workspace,
                    read_input,
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
                        console_settings,
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
            if task.casefold() == "/memory":
                _show_memory(memory_store, output)
                continue
            if task.casefold() in {"/", "/help"}:
                _show_help(output)
                continue
            if task.casefold() == "/verbose":
                console_settings.verbose = not console_settings.verbose
                state = "on" if console_settings.verbose else "off"
                print(f"Verbose tool output: {state}.", file=output)
                continue
            if task.casefold() == "/status":
                _show_workspace_status(workspace_tracker, output)
                continue
            if task.casefold() == "/diff":
                print(workspace_tracker.diff(), file=output)
                continue
            if task.casefold() == "/remember" or task.casefold().startswith(
                "/remember "
            ):
                note = task[len("/remember") :].strip()
                if not note:
                    print("Usage: /remember <project note>", file=output)
                elif memory_store.add(note):
                    print("Project memory updated.", file=output)
                else:
                    print("That note is already in project memory.", file=output)
                continue
            if task.startswith("/"):
                print("Unknown command. Type /help to list commands.", file=output)
                continue
            if not task:
                continue
            try:
                agent_task, references = _attach_file_references(
                    task,
                    workspace,
                )
            except ValueError as exc:
                print(f"Error: {exc}", file=output)
                continue
            if references:
                print(
                    f"[context] Attached {len(references)} file(s).",
                    file=output,
                )
            workspace_tracker.start()
            _run_turn(
                agent_task,
                loop,
                session,
                session_store,
                output,
                _system_prompt(memory_store.items()),
            )
    except (
        ModelClientError,
        ModelConfigError,
        OSError,
        SessionError,
        ValueError,
    ) as exc:
        print(f"Error: {_user_error_message(exc)}", file=output)
        return 1


def _system_prompt(memory: Sequence[str]) -> str:
    if not memory:
        return SYSTEM_PROMPT
    notes = "\n".join(f"- {item}" for item in memory)
    return f"{SYSTEM_PROMPT}\n\nProject memory:\n{notes}"


def _show_memory(store: ProjectMemoryStore, output: TextIO) -> None:
    notes = store.items()
    if not notes:
        print("Project memory is empty.", file=output)
        return
    print("Project memory", file=output)
    for note in notes:
        print(f"  - {note}", file=output)


def _show_help(output: TextIO) -> None:
    print("Available commands", file=output)
    width = max(len(command.usage) for command in SLASH_COMMANDS)
    for command in SLASH_COMMANDS:
        print(
            f"  {command.usage:<{width}}  {command.description}",
            file=output,
        )


def _show_workspace_status(tracker: WorkspaceTracker, output: TextIO) -> None:
    if not tracker.started:
        print("No task changes to show yet.", file=output)
        return

    changes = tracker.changes()
    if changes.empty:
        print("No workspace changes.", file=output)
        return

    print("Workspace changes", file=output)
    for marker, paths in (
        ("A", changes.added),
        ("M", changes.modified),
        ("D", changes.deleted),
    ):
        for path in paths:
            print(f"  {marker} {path}", file=output)


def _create_loop(
    model_client: ModelClient,
    workspace: Path,
    max_steps: int,
    session: Session,
    context_manager: ContextManager,
    output: TextIO,
    console_settings: ConsoleSettings | None = None,
) -> AgentLoop:
    executor = ToolExecutor(workspace)
    return AgentLoop(
        model_client,
        tools=executor.definitions,
        tool_executor=ConsoleToolExecutor(executor, output, console_settings),
        max_steps=max_steps,
        history=session.messages,
        context_manager=context_manager,
    )


def _select_session(
    store: SessionStore,
    current_session_id: str,
    workspace: Path,
    input_fn: Callable[[str], str],
    output: TextIO,
) -> Session | None:
    sessions = [
        session
        for session in store.list_recent(workspace=workspace)
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
    system_prompt: str = SYSTEM_PROMPT,
) -> int:
    """Run and save one turn of a conversation."""

    try:
        answer = loop.run(task, system_prompt=system_prompt)
    except AgentLoopError as exc:
        session.messages = loop.messages
        session.total_turns += 1
        session_store.save(session)
        print(f"Error: {_user_error_message(exc)}", file=output)
        return 1

    session.messages = loop.messages
    session.total_turns += 1
    session_store.save(session)
    print("Agent>", file=output)
    print(answer or "(No final response.)", file=output)
    print(file=output)
    return 0


def main() -> None:
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
