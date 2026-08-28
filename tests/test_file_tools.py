import tempfile
import unittest
from pathlib import Path

from tools import ToolExecutor, read_file


class ReadFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_directory.name) / "workspace"
        self.workspace.mkdir()

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_reads_utf8_file(self) -> None:
        (self.workspace / "hello.txt").write_text("hello\n世界\n", encoding="utf-8")

        result = read_file(self.workspace, "hello.txt")

        self.assertTrue(result.success)
        self.assertEqual(result.content, "hello\n世界\n")
        self.assertIsNone(result.error_type)

    def test_reads_selected_lines(self) -> None:
        (self.workspace / "lines.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")

        result = read_file(self.workspace, "lines.txt", start_line=2, end_line=3)

        self.assertTrue(result.success)
        self.assertEqual(result.content, "two\nthree\n")

    def test_returns_error_for_missing_file(self) -> None:
        result = read_file(self.workspace, "missing.txt")

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "FileNotFound")

    def test_rejects_path_outside_workspace(self) -> None:
        outside = Path(self.temp_directory.name) / "outside.txt"
        outside.write_text("secret", encoding="utf-8")

        result = read_file(self.workspace, "../outside.txt")

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "PathOutsideWorkspace")

    def test_limits_returned_content(self) -> None:
        (self.workspace / "large.txt").write_text("abcdefghij", encoding="utf-8")

        result = read_file(self.workspace, "large.txt", max_chars=5)

        self.assertTrue(result.success)
        self.assertEqual(result.content, "abcde")

    def test_executor_returns_serializable_result(self) -> None:
        (self.workspace / "hello.txt").write_text("hello", encoding="utf-8")
        executor = ToolExecutor(self.workspace)

        result = executor("read_file", {"path": "hello.txt"})

        self.assertEqual(
            result,
            {"success": True, "content": "hello", "error_type": None},
        )


if __name__ == "__main__":
    unittest.main()
