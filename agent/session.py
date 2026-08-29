"""Persistent conversation sessions."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class SessionError(RuntimeError):
    """Raised when a conversation session cannot be loaded or saved."""


@dataclass
class Session:
    """Messages and metadata for one conversation."""

    session_id: str
    created_at: str
    updated_at: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    title: str = ""
    total_turns: int = 0

    @property
    def display_title(self) -> str:
        if self.title:
            return self.title
        for message in self.messages:
            if message.get("role") == "user" and isinstance(message.get("content"), str):
                title = " ".join(message["content"].split())
                return title[:60] or "Untitled session"
        return "Untitled session"

    @property
    def turn_count(self) -> int:
        return self.total_turns


class SessionStore:
    """Save and load conversation sessions as JSON files."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def create(self) -> Session:
        timestamp = datetime.now(timezone.utc)
        session_id = f"{timestamp:%Y%m%d-%H%M%S}-{uuid4().hex[:8]}"
        now = timestamp.isoformat()
        return Session(session_id, now, now)

    def save(self, session: Session) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        if not session.title:
            session.title = session.display_title
        session.total_turns = max(
            session.total_turns,
            sum(message.get("role") == "user" for message in session.messages),
        )
        session.updated_at = datetime.now(timezone.utc).isoformat()
        path = self._path(session.session_id)
        path.write_text(
            json.dumps(asdict(session), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self, session_id: str) -> Session:
        path = self._path(session_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            messages = data.get("messages", [])
            return Session(
                session_id=data["session_id"],
                created_at=data["created_at"],
                updated_at=data["updated_at"],
                messages=messages,
                title=data.get("title", ""),
                total_turns=data.get(
                    "total_turns",
                    sum(message.get("role") == "user" for message in messages),
                ),
            )
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise SessionError(f"Could not load session '{session_id}'.") from exc

    def list_recent(self, limit: int = 10) -> list[Session]:
        paths = sorted(
            self.directory.glob("*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        sessions = []
        for path in paths:
            try:
                sessions.append(self.load(path.stem))
            except SessionError:
                continue
            if len(sessions) == limit:
                break
        return sessions

    def _path(self, session_id: str) -> Path:
        if not SESSION_ID_PATTERN.fullmatch(session_id):
            raise SessionError("Invalid session ID.")
        return self.directory / f"{session_id}.json"
