"""Installed command-line entry point for Code Harness."""

from __future__ import annotations

from collections.abc import Sequence

from cli.app import run_cli


def main(argv: Sequence[str] | None = None) -> int:
    """Start the Code Harness command-line application."""

    return run_cli(argv)
