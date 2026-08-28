import json
import sys
import tempfile
import unittest
from pathlib import Path

from tools import ToolExecutor, run_command


class RunCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_directory.name) / "workspace"
        self.workspace.mkdir()

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_runs_command_in_workspace(self) -> None:
        result = run_command(
            self.workspace,
            [sys.executable, "-B", "-c", "import os; print(os.getcwd())"],
        )
        details = json.loads(result.content)

        self.assertTrue(result.success)
        self.assertEqual(
            details["command"],
            [sys.executable, "-B", "-c", "import os; print(os.getcwd())"],
        )
        self.assertEqual(details["exit_code"], 0)
        self.assertEqual(Path(details["stdout"].strip()), self.workspace)
        self.assertEqual(details["stderr"], "")
        self.assertGreaterEqual(details["duration"], 0)

    def test_returns_nonzero_exit_as_failure(self) -> None:
        result = run_command(
            self.workspace,
            [
                sys.executable,
                "-B",
                "-c",
                "import sys; print('failed'); sys.exit(3)",
            ],
        )
        details = json.loads(result.content)

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "CommandFailed")
        self.assertEqual(details["exit_code"], 3)
        self.assertEqual(details["stdout"], "failed\n")

    def test_stops_command_after_timeout(self) -> None:
        result = run_command(
            self.workspace,
            [sys.executable, "-B", "-c", "import time; time.sleep(2)"],
            timeout=0.1,
        )
        details = json.loads(result.content)

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "CommandTimeout")
        self.assertIsNone(details["exit_code"])

    def test_limits_stdout_and_stderr(self) -> None:
        result = run_command(
            self.workspace,
            [
                sys.executable,
                "-B",
                "-c",
                "import sys; print('x' * 50); print('y' * 50, file=sys.stderr)",
            ],
            max_output_chars=20,
        )
        details = json.loads(result.content)

        self.assertTrue(result.success)
        self.assertLessEqual(len(details["stdout"]), 20)
        self.assertLessEqual(len(details["stderr"]), 20)
        self.assertTrue(details["stdout"].endswith("...[truncated]"))
        self.assertTrue(details["stderr"].endswith("...[truncated]"))

    def test_rejects_string_command(self) -> None:
        result = run_command(self.workspace, "python --version")

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "InvalidArguments")

    def test_executor_exposes_and_runs_command_tool(self) -> None:
        executor = ToolExecutor(self.workspace)

        names = [definition["function"]["name"] for definition in executor.definitions]
        result = executor(
            "run_command",
            {"command": [sys.executable, "-B", "-c", "print('ok')"]},
        )
        details = json.loads(result["content"])

        self.assertIn("run_command", names)
        self.assertTrue(result["success"])
        self.assertEqual(details["stdout"], "ok\n")


if __name__ == "__main__":
    unittest.main()
