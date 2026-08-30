"""Interactive input and command completion."""

from __future__ import annotations

import re
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

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


DEFAULT_HISTORY_FILE = Path(".agent/history")


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
    SlashCommand("/plan", "/plan <task>", "Explore and create a read-only plan"),
    SlashCommand("/act", "/act", "Execute the latest plan"),
    SlashCommand("/cancel", "/cancel", "Discard the current plan"),
    SlashCommand("/help", "/help", "Show available commands"),
    SlashCommand("/exit", "/exit", "Save the session and exit"),
)


class SlashCommandCompleter(Completer):
    """Complete commands and workspace file references."""

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
        complete_event: CompleteEvent,
    ) -> Iterator[Completion]:
        text = document.text_before_cursor
        if text.casefold().startswith("/open "):
            path_text = text[len("/open ") :]
            yield from self._path_completer.get_completions(
                Document(path_text, cursor_position=len(path_text)),
                complete_event,
            )
            return

        reference = re.search(r"(?:^|\s)@([^\s]*)$", text)
        if reference is not None and self._workspace_getter is not None:
            path_text = reference.group(1)
            yield from self._file_completer.get_completions(
                Document(path_text, cursor_position=len(path_text)),
                complete_event,
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


def interactive_input(
    input_fn: Callable[[str], str],
    workspace_getter: Callable[[], Path] | None = None,
) -> Callable[[str], str]:
    if input_fn is not input or not sys.stdin.isatty():
        return input_fn

    task_session = task_prompt_session(
        DEFAULT_HISTORY_FILE,
        workspace_getter=workspace_getter,
    )
    choice_session: PromptSession[str] = PromptSession()

    def read(prompt: str) -> str:
        session = (
            task_session
            if prompt in {"Task> ", "Plan> "}
            else choice_session
        )
        return session.prompt(prompt)

    return read


def task_prompt_session(
    history_file: Path,
    *,
    workspace_getter: Callable[[], Path] | None = None,
    prompt_input: Input | None = None,
    prompt_output: Output | None = None,
) -> PromptSession[str]:
    history_file.parent.mkdir(parents=True, exist_ok=True)
    return PromptSession(
        history=FileHistory(str(history_file)),
        completer=SlashCommandCompleter(workspace_getter),
        complete_while_typing=True,
        complete_style=CompleteStyle.MULTI_COLUMN,
        input=prompt_input,
        output=prompt_output,
    )
