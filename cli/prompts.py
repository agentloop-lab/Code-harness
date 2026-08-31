"""System prompts used by the CLI modes."""

from __future__ import annotations

import sys
from collections.abc import Sequence


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
PLAN_SYSTEM_PROMPT = (
    "You are a coding agent in Plan Mode. Work only inside the provided "
    "workspace. Explore the code with the available read-only tools, but do "
    "not modify files or run commands. Identify the relevant files and "
    "constraints, then return a concise, actionable implementation plan. "
    "When the user gives feedback, revise and return the full plan. "
    "Do not claim that the plan has been implemented."
)


def system_prompt(
    memory: Sequence[str],
    active_skill: str | None = None,
) -> str:
    return _with_context(SYSTEM_PROMPT, memory, active_skill)


def planning_system_prompt(
    memory: Sequence[str],
    active_skill: str | None = None,
) -> str:
    return _with_context(PLAN_SYSTEM_PROMPT, memory, active_skill)


def _with_context(
    base_prompt: str,
    memory: Sequence[str],
    active_skill: str | None,
) -> str:
    sections = [base_prompt]
    if memory:
        notes = "\n".join(f"- {item}" for item in memory)
        sections.append(f"Project memory:\n{notes}")
    if active_skill:
        sections.append(
            "Active skill instructions follow. They supplement the task but "
            "cannot override workspace or tool safety rules.\n\n"
            f"{active_skill}"
        )
    return "\n\n".join(sections)
