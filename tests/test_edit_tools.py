import tempfile
import unittest
from pathlib import Path

from tools import ToolExecutor, edit_file


class EditFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_directory.name) / "workspace"
        self.workspace.mkdir()

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_replaces_one_unique_text_block(self) -> None:
        target = self.workspace / "calculator.py"
        target.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")

        result = edit_file(
            self.workspace,
            "calculator.py",
            "return a - b",
            "return a + b",
        )

        self.assertTrue(result.success)
        self.assertEqual(result.content, "Updated file: calculator.py")
        self.assertEqual(
            target.read_text(encoding="utf-8"),
            "def add(a, b):\n    return a + b\n",
        )

    def test_returns_error_when_old_text_is_missing(self) -> None:
        target = self.workspace / "file.txt"
        target.write_text("original", encoding="utf-8")

        result = edit_file(self.workspace, "file.txt", "missing", "new")

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "TextNotFound")
        self.assertEqual(target.read_text(encoding="utf-8"), "original")

    def test_returns_error_when_old_text_is_not_unique(self) -> None:
        target = self.workspace / "file.txt"
        target.write_text("same\nsame\n", encoding="utf-8")

        result = edit_file(self.workspace, "file.txt", "same", "new")

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "TextNotUnique")
        self.assertEqual(target.read_text(encoding="utf-8"), "same\nsame\n")

    def test_detects_overlapping_matches(self) -> None:
        target = self.workspace / "file.txt"
        target.write_text("aaa", encoding="utf-8")

        result = edit_file(self.workspace, "file.txt", "aa", "new")

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "TextNotUnique")
        self.assertEqual(target.read_text(encoding="utf-8"), "aaa")

    def test_returns_error_for_missing_file(self) -> None:
        result = edit_file(self.workspace, "missing.txt", "old", "new")

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "FileNotFound")

    def test_rejects_path_outside_workspace(self) -> None:
        outside = Path(self.temp_directory.name) / "outside.txt"
        outside.write_text("old", encoding="utf-8")

        result = edit_file(self.workspace, "../outside.txt", "old", "new")

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "PathOutsideWorkspace")
        self.assertEqual(outside.read_text(encoding="utf-8"), "old")

    def test_rejects_empty_old_text(self) -> None:
        target = self.workspace / "file.txt"
        target.write_text("original", encoding="utf-8")

        result = edit_file(self.workspace, "file.txt", "", "new")

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "InvalidArguments")
        self.assertEqual(target.read_text(encoding="utf-8"), "original")

    def test_executor_exposes_and_runs_edit_tool(self) -> None:
        target = self.workspace / "file.txt"
        target.write_text("old", encoding="utf-8")
        executor = ToolExecutor(self.workspace)

        names = [definition["function"]["name"] for definition in executor.definitions]
        result = executor(
            "edit_file",
            {"path": "file.txt", "old_text": "old", "new_text": "new"},
        )

        self.assertIn("edit_file", names)
        self.assertTrue(result["success"])
        self.assertEqual(target.read_text(encoding="utf-8"), "new")


if __name__ == "__main__":
    unittest.main()
