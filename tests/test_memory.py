import tempfile
import unittest
from pathlib import Path

from agent.memory import ProjectMemoryStore


class ProjectMemoryStoreTests(unittest.TestCase):
    def test_persists_unique_project_notes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "memory.md"
            store = ProjectMemoryStore(path)

            self.assertTrue(store.add("Use pytest for tests."))
            self.assertFalse(store.add("Use pytest for tests."))
            loaded = ProjectMemoryStore(path).items()

        self.assertEqual(loaded, ["Use pytest for tests."])


if __name__ == "__main__":
    unittest.main()
