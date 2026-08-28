import tempfile
import unittest
from pathlib import Path

from tools import ToolExecutor, write_file


class WriteFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_directory.name) / "workspace"
        self.workspace.mkdir()

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_creates_utf8_file_and_parent_directories(self) -> None:
        result = write_file(self.workspace, "src/hello.txt", "hello\n世界\n")

        self.assertTrue(result.success)
        self.assertEqual(result.content, "Created file: src/hello.txt")
        self.assertEqual(
            (self.workspace / "src" / "hello.txt").read_text(encoding="utf-8"),
            "hello\n世界\n",
        )

    def test_does_not_overwrite_existing_file(self) -> None:
        target = self.workspace / "existing.txt"
        target.write_text("original", encoding="utf-8")

        result = write_file(self.workspace, "existing.txt", "replacement")

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "FileAlreadyExists")
        self.assertEqual(target.read_text(encoding="utf-8"), "original")

    def test_rejects_path_outside_workspace(self) -> None:
        outside = Path(self.temp_directory.name) / "outside.txt"

        result = write_file(self.workspace, "../outside.txt", "secret")

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "PathOutsideWorkspace")
        self.assertFalse(outside.exists())

    def test_rejects_invalid_arguments(self) -> None:
        result = write_file(self.workspace, "", "content")

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "InvalidArguments")

    def test_executor_exposes_and_runs_write_tool(self) -> None:
        executor = ToolExecutor(self.workspace)

        names = [definition["function"]["name"] for definition in executor.definitions]
        result = executor(
            "write_file",
            {"path": "created.txt", "content": "created"},
        )

        self.assertIn("write_file", names)
        self.assertTrue(result["success"])
        self.assertEqual(
            (self.workspace / "created.txt").read_text(encoding="utf-8"),
            "created",
        )


if __name__ == "__main__":
    unittest.main()
