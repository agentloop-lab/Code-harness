import tempfile
import unittest
from pathlib import Path

from agent.workspace import WorkspaceTracker


class WorkspaceTrackerTests(unittest.TestCase):
    def test_reports_file_changes_and_builds_text_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            (workspace / "modified.txt").write_text("old\n", encoding="utf-8")
            (workspace / "deleted.txt").write_text("gone\n", encoding="utf-8")
            tracker = WorkspaceTracker(workspace)
            tracker.start()

            (workspace / "modified.txt").write_text("new\n", encoding="utf-8")
            (workspace / "deleted.txt").unlink()
            (workspace / "added.txt").write_text("added\n", encoding="utf-8")

            changes = tracker.changes()
            diff = tracker.diff()

        self.assertEqual(changes.added, ("added.txt",))
        self.assertEqual(changes.modified, ("modified.txt",))
        self.assertEqual(changes.deleted, ("deleted.txt",))
        self.assertIn("+++ b/added.txt", diff)
        self.assertIn("-old", diff)
        self.assertIn("+new", diff)
        self.assertIn("+++ /dev/null", diff)


if __name__ == "__main__":
    unittest.main()
