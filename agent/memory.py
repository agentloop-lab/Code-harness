"""Persistent project memory storage."""

from __future__ import annotations

from pathlib import Path


MEMORY_HEADER = "# Project Memory"


class ProjectMemoryStore:
    """Store explicit long-term project notes in a Markdown file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def items(self) -> list[str]:
        if not self.path.exists():
            return []
        return [
            line[2:].strip()
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.startswith("- ") and line[2:].strip()
        ]

    def add(self, note: str) -> bool:
        note = " ".join(note.split())
        notes = self.items()
        if note in notes:
            return False

        notes.append(note)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        content = f"{MEMORY_HEADER}\n\n" + "\n".join(
            f"- {item}" for item in notes
        )
        self.path.write_text(f"{content}\n", encoding="utf-8")
        return True
