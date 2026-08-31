"""Discover and load reusable Agent Skills."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


NAME_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
HEADER_LIMIT = 4096


class SkillError(ValueError):
    """Raised when a skill package is invalid or unavailable."""


@dataclass(frozen=True)
class SkillSummary:
    name: str
    description: str
    path: Path


@dataclass(frozen=True)
class Skill(SkillSummary):
    instructions: str


class SkillStore:
    """Load SKILL.md packages from configured directories."""

    def __init__(self, roots: Sequence[str | Path]) -> None:
        self.roots = [Path(root) for root in roots]

    def summaries(self) -> list[SkillSummary]:
        found: dict[str, SkillSummary] = {}
        for root in self.roots:
            if not root.is_dir():
                continue
            for skill_file in sorted(root.glob("*/SKILL.md")):
                try:
                    summary = self._read_summary(skill_file)
                except (OSError, UnicodeError, SkillError):
                    continue
                found[summary.name] = summary
        return sorted(found.values(), key=lambda skill: skill.name)

    def names(self) -> list[str]:
        return [skill.name for skill in self.summaries()]

    def load(self, name: str) -> Skill:
        if NAME_PATTERN.fullmatch(name) is None:
            raise SkillError(f"Invalid skill name: {name}")

        for root in reversed(self.roots):
            skill_file = root / name / "SKILL.md"
            if not skill_file.is_file():
                continue
            summary = self._read_summary(skill_file)
            content = skill_file.read_text(encoding="utf-8")
            _, instructions = self._split_document(content)
            instructions = instructions.strip()
            if not instructions:
                raise SkillError(f"Skill has no instructions: {name}")
            return Skill(
                summary.name,
                summary.description,
                summary.path,
                instructions,
            )
        raise SkillError(f"Skill not found: {name}")

    def _read_summary(self, skill_file: Path) -> SkillSummary:
        with skill_file.open("r", encoding="utf-8") as handle:
            if handle.readline().rstrip("\r\n") != "---":
                raise SkillError("SKILL.md must start with YAML frontmatter.")
            header_lines = []
            header_size = 0
            for line in handle:
                if line.rstrip("\r\n") == "---":
                    break
                header_size += len(line)
                if header_size > HEADER_LIMIT:
                    raise SkillError("SKILL.md frontmatter is too large.")
                header_lines.append(line)
            else:
                raise SkillError("SKILL.md frontmatter is not closed.")
        header = "".join(header_lines)
        fields = self._parse_header(header)
        name = fields.get("name", "")
        description = fields.get("description", "")

        if NAME_PATTERN.fullmatch(name) is None or len(name) > 64:
            raise SkillError(f"Invalid skill name in {skill_file}")
        if name != skill_file.parent.name:
            raise SkillError(f"Skill name must match its directory: {name}")
        if not description or len(description) > 1024:
            raise SkillError(f"Invalid skill description in {skill_file}")
        return SkillSummary(name, description, skill_file)

    @staticmethod
    def _split_document(content: str) -> tuple[str, str]:
        normalized = content.replace("\r\n", "\n")
        if not normalized.startswith("---\n"):
            raise SkillError("SKILL.md must start with YAML frontmatter.")
        closing = normalized.find("\n---\n", 4)
        if closing == -1:
            raise SkillError("SKILL.md frontmatter is not closed.")
        return normalized[4:closing], normalized[closing + 5 :]

    @staticmethod
    def _parse_header(header: str) -> dict[str, str]:
        fields: dict[str, str] = {}
        for line in header.splitlines():
            if not line.strip() or line.startswith((" ", "\t")):
                continue
            key, separator, value = line.partition(":")
            if not separator:
                continue
            value = value.strip()
            if (
                len(value) >= 2
                and value[0] == value[-1]
                and value[0] in {'"', "'"}
            ):
                value = value[1:-1]
            fields[key.strip()] = value
        return fields
