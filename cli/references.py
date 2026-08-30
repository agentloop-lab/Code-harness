"""Attach explicit workspace file references to a task."""

from __future__ import annotations

import re
from pathlib import Path

from tools import read_file


FILE_REFERENCE_PATTERN = re.compile(r"(?<!\S)@([^\s]+)")
MAX_REFERENCE_FILES = 5
MAX_REFERENCE_CHARS = 30_000
MAX_REFERENCE_FILE_CHARS = 6_000


def attach_file_references(
    task: str,
    workspace: Path,
) -> tuple[str, list[str]]:
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
