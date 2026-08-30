import tempfile
import unittest
from pathlib import Path

from agent.session import SessionStore


class SessionStoreTests(unittest.TestCase):
    def test_saves_and_loads_conversation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = SessionStore(Path(temporary_directory))
            workspace = Path(temporary_directory) / "project"
            session = store.create(workspace)
            session.messages = [{"role": "user", "content": "Hello"}]

            store.save(session)
            loaded = store.load(session.session_id)

        self.assertEqual(loaded.session_id, session.session_id)
        self.assertEqual(loaded.messages, session.messages)
        self.assertEqual(loaded.display_title, "Hello")
        self.assertEqual(loaded.turn_count, 1)
        self.assertEqual(loaded.workspace, str(workspace.resolve()))

    def test_lists_sessions_from_one_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            store = SessionStore(root / "sessions")
            first = store.create(root / "first")
            second = store.create(root / "second")
            store.save(first)
            store.save(second)

            sessions = store.list_recent(workspace=root / "first")

        self.assertEqual(
            [session.session_id for session in sessions],
            [first.session_id],
        )

if __name__ == "__main__":
    unittest.main()
