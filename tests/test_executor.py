import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import ToolExecutor
from tools.executor import READ_ONLY_TOOLS


class ToolExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_directory.name) / "workspace"
        self.workspace.mkdir()
        self.executor = ToolExecutor(self.workspace)

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_returns_error_for_unknown_tool(self) -> None:
        result = self.executor("missing_tool", {})

        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "UnknownTool")

    def test_read_only_executor_hides_and_rejects_write_tools(self) -> None:
        executor = ToolExecutor(self.workspace, allowed_tools=READ_ONLY_TOOLS)

        names = {
            definition["function"]["name"]
            for definition in executor.definitions
        }
        result = executor("write_file", {"path": "new.py", "content": ""})

        self.assertEqual(names, READ_ONLY_TOOLS)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "ToolUnavailable")
        self.assertFalse((self.workspace / "new.py").exists())

    def test_returns_error_for_missing_arguments(self) -> None:
        result = self.executor("read_file", {})

        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "InvalidArguments")

    def test_returns_error_for_extra_arguments(self) -> None:
        result = self.executor(
            "read_file",
            {"path": "file.txt", "unexpected": True},
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "InvalidArguments")

    def test_returns_error_for_non_mapping_arguments(self) -> None:
        result = self.executor("read_file", ["file.txt"])

        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "InvalidArguments")

    @patch("tools.executor.read_file_snapshot", side_effect=RuntimeError("unexpected"))
    def test_returns_error_for_unexpected_tool_exception(self, snapshot_mock) -> None:
        result = self.executor("read_file", {"path": "file.txt"})

        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "ToolError")


if __name__ == "__main__":
    unittest.main()
