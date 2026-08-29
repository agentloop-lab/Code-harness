import tempfile
import unittest
from pathlib import Path

from tools import ToolExecutor, list_files


class ListFilesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_directory.name) / "workspace"
        self.workspace.mkdir()

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_lists_files_recursively(self) -> None:
        (self.workspace / "notes.txt").write_text("notes", encoding="utf-8")
        source_directory = self.workspace / "src"
        source_directory.mkdir()
        (source_directory / "main.py").write_text("pass\n", encoding="utf-8")

        result = list_files(self.workspace)

        self.assertTrue(result.success)
        self.assertEqual(result.content, "notes.txt\nsrc/main.py")

    def test_can_list_only_the_selected_directory(self) -> None:
        (self.workspace / "top.txt").write_text("top", encoding="utf-8")
        nested_directory = self.workspace / "nested"
        nested_directory.mkdir()
        (nested_directory / "inside.txt").write_text("inside", encoding="utf-8")

        result = list_files(self.workspace, recursive=False)

        self.assertTrue(result.success)
        self.assertEqual(result.content, "top.txt")

    def test_reports_an_empty_directory(self) -> None:
        result = list_files(self.workspace)

        self.assertTrue(result.success)
        self.assertEqual(result.content, "No files found.")

    def test_rejects_path_outside_workspace(self) -> None:
        result = list_files(self.workspace, "..")

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "PathOutsideWorkspace")

    def test_limits_number_of_files(self) -> None:
        for index in range(3):
            (self.workspace / f"{index}.txt").write_text("", encoding="utf-8")

        result = list_files(self.workspace, max_results=2)

        self.assertTrue(result.success)
        self.assertEqual(result.content, "0.txt\n1.txt\n...[truncated]")

    def test_executor_exposes_and_runs_list_files(self) -> None:
        (self.workspace / "notes.txt").write_text("notes", encoding="utf-8")
        executor = ToolExecutor(self.workspace)

        names = [definition["function"]["name"] for definition in executor.definitions]
        result = executor("list_files", {})

        self.assertIn("list_files", names)
        self.assertTrue(result["success"])
        self.assertEqual(result["content"], "notes.txt")


if __name__ == "__main__":
    unittest.main()
