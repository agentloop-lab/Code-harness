"""Track workspace changes for the current task."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path


@dataclass(frozen=True)
class WorkspaceChanges:
    added: tuple[str, ...]
    modified: tuple[str, ...]
    deleted: tuple[str, ...]

    @property
    def empty(self) -> bool:
        return not (self.added or self.modified or self.deleted)


class WorkspaceTracker:
    """Compare the workspace with its state before the latest task."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self._before: dict[str, bytes] | None = None

    @property
    def started(self) -> bool:
        return self._before is not None

    def start(self) -> None:
        self._before = self._snapshot()

    def changes(self) -> WorkspaceChanges:
        if self._before is None:
            return WorkspaceChanges((), (), ())
        return self._compare(self._snapshot())

    def _compare(self, after: dict[str, bytes]) -> WorkspaceChanges:
        assert self._before is not None
        before_paths = set(self._before)
        after_paths = set(after)
        return WorkspaceChanges(
            added=tuple(sorted(after_paths - before_paths)),
            modified=tuple(
                sorted(
                    path
                    for path in before_paths & after_paths
                    if self._before[path] != after[path]
                )
            ),
            deleted=tuple(sorted(before_paths - after_paths)),
        )

    def diff(self) -> str:
        if self._before is None:
            return "No task changes to show yet."

        after = self._snapshot()
        changes = self._compare(after)
        if changes.empty:
            return "No workspace changes."

        sections: list[str] = []
        for path in (*changes.added, *changes.modified, *changes.deleted):
            old_content = self._before.get(path, b"")
            new_content = after.get(path, b"")
            try:
                old_text = old_content.decode("utf-8")
                new_text = new_content.decode("utf-8")
            except UnicodeDecodeError:
                sections.append(f"Binary file changed: {path}")
                continue

            from_file = f"a/{path}" if path in self._before else "/dev/null"
            to_file = f"b/{path}" if path in after else "/dev/null"
            sections.append(
                "".join(
                    unified_diff(
                        old_text.splitlines(keepends=True),
                        new_text.splitlines(keepends=True),
                        fromfile=from_file,
                        tofile=to_file,
                    )
                )
            )
        return "\n".join(section.rstrip() for section in sections)

    def _snapshot(self) -> dict[str, bytes]:
        return {
            path.relative_to(self.workspace).as_posix(): path.read_bytes()
            for path in self.workspace.rglob("*")
            if path.is_file()
        }
