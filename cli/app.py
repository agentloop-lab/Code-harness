"""Code Harness command-line application."""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import TextIO

from agent.context import ContextError, ContextManager
from agent.loop import AgentLoop, AgentLoopError
from agent.memory import ProjectMemoryStore
from agent.model import ModelClient, ModelClientError, ModelConfigError
from agent.session import Session, SessionError, SessionStore
from agent.skills import Skill, SkillError, SkillStore
from agent.workspace import WorkspaceTracker
from cli.completion import (
    SLASH_COMMANDS,
    SlashCommandCompleter,
    interactive_input as _interactive_input,
    task_prompt_session as _task_prompt_session,
)
from cli.console import ConsoleSettings, ConsoleToolExecutor
from cli.prompts import (
    PLAN_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    planning_system_prompt as _planning_system_prompt,
    system_prompt as _system_prompt,
)
from cli.references import attach_file_references as _attach_file_references
from tools import ToolExecutor
from tools.executor import READ_ONLY_TOOLS


DEFAULT_SESSION_DIRECTORY = Path(".agent/sessions")
DEFAULT_RESULT_DIRECTORY = Path(".agent/results")
DEFAULT_MEMORY_FILE = Path(".agent/memory.md")
DEFAULT_PROJECT_DIRECTORY = Path(".agent/projects")
DEFAULT_SKILL_DIRECTORIES = (Path("skills"), Path(".agent/skills"))
EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit"}


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


def _memory_file_for_workspace(workspace: Path) -> Path:
    resolved = workspace.resolve()
    if resolved == Path("workspace").resolve():
        return DEFAULT_MEMORY_FILE
    key = hashlib.sha256(
        str(resolved).casefold().encode("utf-8")
    ).hexdigest()[:16]
    return DEFAULT_PROJECT_DIRECTORY / key / "memory.md"


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
        skill_store = SkillStore(DEFAULT_SKILL_DIRECTORIES)
        active_skill: Skill | None = None
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
        pending_plan: str | None = None
        planning_loop: AgentLoop | None = None
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
                _system_prompt(
                    memory_store.items(),
                    _skill_instructions(active_skill),
                ),
            )

        read_input = _interactive_input(
            input_fn,
            lambda: workspace,
            skill_store.names,
        )
        print("Commands: type / for help and completion", file=output)
        while True:
            try:
                prompt = "Plan> " if planning_loop is not None else "Task> "
                task = read_input(prompt).strip()
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
                pending_plan = None
                planning_loop = None
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
                    pending_plan = None
                    planning_loop = None
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
                    planning_loop or loop,
                    session,
                    session_store,
                    output,
                )
                if planning_loop is not None:
                    loop.messages = planning_loop.messages
                continue
            if task.casefold() == "/memory":
                _show_memory(memory_store, output)
                continue
            if task.casefold() == "/skills":
                _show_skills(skill_store, active_skill, output)
                continue
            if task.casefold() == "/skill" or task.casefold().startswith(
                "/skill "
            ):
                name = task[len("/skill") :].strip()
                if not name:
                    print("Usage: /skill <name|off>", file=output)
                    continue
                if name.casefold() == "off":
                    active_skill = None
                    print("Active skill: none.", file=output)
                    continue
                try:
                    active_skill = skill_store.load(name)
                except (OSError, UnicodeError, SkillError) as exc:
                    print(f"Error: {exc}", file=output)
                    continue
                print(f"Active skill: {active_skill.name}.", file=output)
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
            if task.casefold() == "/cancel":
                if planning_loop is None and not pending_plan:
                    print("No active plan.", file=output)
                else:
                    planning_loop = None
                    pending_plan = None
                    print("Plan cancelled.", file=output)
                continue
            if task.casefold() == "/plan" or task.casefold().startswith(
                "/plan "
            ):
                plan_task = task[len("/plan") :].strip()
                if not plan_task:
                    print("Usage: /plan <task>", file=output)
                    continue
                try:
                    agent_task, references = _attach_file_references(
                        plan_task,
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
                planning_loop = _create_loop(
                    model_client,
                    workspace,
                    args.max_steps,
                    session,
                    context_manager,
                    output,
                    console_settings,
                    allowed_tools=READ_ONLY_TOOLS,
                )
                result = _run_turn(
                    agent_task,
                    planning_loop,
                    session,
                    session_store,
                    output,
                    _planning_system_prompt(
                        memory_store.items(),
                        _skill_instructions(active_skill),
                    ),
                    answer_label="Plan>",
                )
                loop.messages = planning_loop.messages
                if result == 0:
                    last_message = planning_loop.messages[-1]
                    content = last_message.get("content")
                    pending_plan = content if isinstance(content, str) else ""
                    print(
                        "Give feedback to revise it, or use /act to execute.",
                        file=output,
                    )
                else:
                    planning_loop = None
                continue
            if task.casefold() == "/act":
                if not pending_plan:
                    print("No plan to execute. Use /plan <task> first.", file=output)
                    continue
                planning_loop = None
                workspace_tracker.start()
                result = _run_turn(
                    "Execute the approved plan below. Inspect files again if "
                    f"needed, make the changes, and verify them.\n\n{pending_plan}",
                    loop,
                    session,
                    session_store,
                    output,
                    _system_prompt(
                        memory_store.items(),
                        _skill_instructions(active_skill),
                    ),
                )
                if result == 0:
                    pending_plan = None
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
            if planning_loop is not None:
                try:
                    feedback, references = _attach_file_references(
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
                result = _run_turn(
                    "Revise the current plan based on this user feedback. "
                    "Continue to use only read-only tools and return the full "
                    f"updated plan.\n\nFeedback:\n{feedback}",
                    planning_loop,
                    session,
                    session_store,
                    output,
                    _planning_system_prompt(
                        memory_store.items(),
                        _skill_instructions(active_skill),
                    ),
                    answer_label="Plan>",
                )
                loop.messages = planning_loop.messages
                if result == 0:
                    last_message = planning_loop.messages[-1]
                    content = last_message.get("content")
                    pending_plan = content if isinstance(content, str) else ""
                    print(
                        "Give more feedback, or use /act to execute.",
                        file=output,
                    )
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
            pending_plan = None
            workspace_tracker.start()
            _run_turn(
                agent_task,
                loop,
                session,
                session_store,
                output,
                _system_prompt(
                    memory_store.items(),
                    _skill_instructions(active_skill),
                ),
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


def _show_memory(store: ProjectMemoryStore, output: TextIO) -> None:
    notes = store.items()
    if not notes:
        print("Project memory is empty.", file=output)
        return
    print("Project memory", file=output)
    for note in notes:
        print(f"  - {note}", file=output)


def _show_skills(
    store: SkillStore,
    active_skill: Skill | None,
    output: TextIO,
) -> None:
    skills = store.summaries()
    if not skills:
        print("No skills found.", file=output)
        return
    print("Available skills", file=output)
    for skill in skills:
        marker = "*" if active_skill and active_skill.name == skill.name else " "
        print(f" {marker} {skill.name} - {skill.description}", file=output)


def _skill_instructions(skill: Skill | None) -> str | None:
    if skill is None:
        return None
    return (
        f"Skill: {skill.name}\n"
        f"Description: {skill.description}\n\n"
        f"{skill.instructions}"
    )


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
    allowed_tools: set[str] | frozenset[str] | None = None,
) -> AgentLoop:
    executor = (
        ToolExecutor(workspace, allowed_tools=allowed_tools)
        if allowed_tools is not None
        else ToolExecutor(workspace)
    )
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
    answer_label: str = "Agent>",
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
    print(answer_label, file=output)
    print(answer or "(No final response.)", file=output)
    print(file=output)
    return 0
