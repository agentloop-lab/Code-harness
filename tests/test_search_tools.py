import tempfile
import unittest
from pathlib import Path

from tools import ToolExecutor, search_text


class SearchTextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_directory.name) / "workspace"
        self.workspace.mkdir()

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_searches_files_recursively(self) -> None:
        source_directory = self.workspace / "src"
        source_directory.mkdir()
        (source_directory / "first.py").write_text(
            "def target():\n    return 1\n", encoding="utf-8"
        )
        (source_directory / "second.py").write_text(
            "value = target()\n", encoding="utf-8"
        )

        result = search_text(self.workspace, "target", "src")

        self.assertTrue(result.success)
        self.assertEqual(
            result.content,
            "src/first.py:1:def target():\nsrc/second.py:1:value = target()",
        )

    def test_searches_one_file(self) -> None:
        (self.workspace / "notes.txt").write_text(
            "first\nfind me\nlast\n", encoding="utf-8"
        )

        result = search_text(self.workspace, "find", "notes.txt")

        self.assertTrue(result.success)
        self.assertEqual(result.content, "notes.txt:2:find me")

    def test_reports_no_matches(self) -> None:
        (self.workspace / "notes.txt").write_text("hello\n", encoding="utf-8")

        result = search_text(self.workspace, "missing")

        self.assertTrue(result.success)
        self.assertEqual(result.content, "No matches found.")

    def test_skips_non_utf8_files(self) -> None:
        (self.workspace / "binary.dat").write_bytes(b"\xff\xfe\x00")
        (self.workspace / "notes.txt").write_text("find me\n", encoding="utf-8")

        result = search_text(self.workspace, "find")

        self.assertTrue(result.success)
        self.assertEqual(result.content, "notes.txt:1:find me")

    def test_rejects_path_outside_workspace(self) -> None:
        outside = Path(self.temp_directory.name) / "outside.txt"
        outside.write_text("target", encoding="utf-8")

        result = search_text(self.workspace, "target", "../outside.txt")

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "PathOutsideWorkspace")

    def test_limits_number_of_matches(self) -> None:
        (self.workspace / "many.txt").write_text(
            "target\ntarget\ntarget\n", encoding="utf-8"
        )

        result = search_text(self.workspace, "target", max_results=2)

        self.assertTrue(result.success)
        self.assertEqual(len(result.content.splitlines()), 2)

    def test_executor_exposes_and_runs_search_tool(self) -> None:
        (self.workspace / "notes.txt").write_text("find me\n", encoding="utf-8")
        executor = ToolExecutor(self.workspace)

        names = [definition["function"]["name"] for definition in executor.definitions]
        result = executor("search_text", {"query": "find"})

        self.assertIn("search_text", names)
        self.assertEqual(result["content"], "notes.txt:1:find me")
        self.assertTrue(result["success"])


if __name__ == "__main__":
    unittest.main()
