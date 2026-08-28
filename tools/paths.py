"""Workspace path validation."""

from __future__ import annotations

from pathlib import Path


class WorkspacePathError(ValueError):
    """Raised when a requested path leaves the workspace."""


def resolve_workspace_path(workspace: str | Path, path: str) -> Path:
    """Resolve a path and ensure it stays within the workspace."""

    root = Path(workspace).resolve()
    requested = Path(path)
    target = (
        requested.resolve()
        if requested.is_absolute()
        else (root / requested).resolve()
    )

    if not is_within_workspace(root, target):
        raise WorkspacePathError("Path is outside the workspace.")
    return target


def is_within_workspace(workspace: str | Path, path: str | Path) -> bool:
    """Return whether a resolved path belongs to the workspace."""

    root = Path(workspace).resolve()
    target = Path(path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return False
    return True
