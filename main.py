"""Command-line entry point for Code Harness."""

from cli.app import run_cli


def main() -> None:
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
