import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from agent.context import ContextManager


def summary_response(content):
    message = SimpleNamespace(content=content)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class ContextManagerTests(unittest.TestCase):
    def test_offloads_only_large_tool_results(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            manager = ContextManager(
                Path(temporary_directory),
                tool_result_limit=20,
                preview_size=10,
            )

            self.assertEqual(manager.process_tool_result("short"), "short")
            compacted = manager.process_tool_result("abcdefghijklmnopqrstuvwxyz")
            result_files = list(Path(temporary_directory).glob("*.txt"))

            self.assertEqual(len(result_files), 1)
            self.assertEqual(
                result_files[0].read_text(encoding="utf-8"),
                "abcdefghijklmnopqrstuvwxyz",
            )
            self.assertIn("Full output stored at", compacted)
            self.assertNotIn("fghijklmnopqrstu", compacted)

    def test_compacts_history_into_one_summary(self) -> None:
        model_client = Mock()
        model_client.chat.return_value = summary_response("- Progress: fixed app.py")
        manager = ContextManager(Path("results"))
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Fix app.py"},
            {"role": "assistant", "content": "Done"},
        ]

        compacted = manager.compact_history(messages, model_client)

        self.assertEqual(len(compacted), 1)
        self.assertIn("System prompt", compacted[0]["content"])
        self.assertIn("fixed app.py", compacted[0]["content"])
        self.assertLess(manager.estimate_size(compacted), manager.estimate_size(messages))


if __name__ == "__main__":
    unittest.main()
