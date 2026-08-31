"""Compatibility entry point for running Code Harness from source."""

from cli.entrypoint import main


if __name__ == "__main__":
    raise SystemExit(main())
