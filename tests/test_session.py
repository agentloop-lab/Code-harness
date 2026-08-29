import tempfile
import unittest
from pathlib import Path

from agent.session import SessionStore


class SessionStoreTests(unittest.TestCase):
    def test_saves_and_loads_conversation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = SessionStore(Path(temporary_directory))
            session = store.create()
            session.messages = [{"role": "user", "content": "Hello"}]

            store.save(session)
            loaded = store.load(session.session_id)

        self.assertEqual(loaded.session_id, session.session_id)
        self.assertEqual(loaded.messages, session.messages)
        self.assertEqual(loaded.display_title, "Hello")
        self.assertEqual(loaded.turn_count, 1)

if __name__ == "__main__":
    unittest.main()
