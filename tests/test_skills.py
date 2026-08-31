import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.skills import SkillError, SkillStore


class SkillStoreTests(unittest.TestCase):
    def test_lists_metadata_without_loading_full_document(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill_directory = root / "python-testing"
            skill_directory.mkdir()
            (skill_directory / "SKILL.md").write_text(
                "---\n"
                "name: python-testing\n"
                "description: Use for Python tests.\n"
                "---\n\n"
                "Run focused tests first.\n",
                encoding="utf-8",
            )
            store = SkillStore([root])

            with patch.object(Path, "read_text", side_effect=AssertionError):
                summaries = store.summaries()

        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].name, "python-testing")
        self.assertEqual(summaries[0].description, "Use for Python tests.")

    def test_loads_instructions_for_a_selected_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill_directory = root / "code-review"
            skill_directory.mkdir()
            (skill_directory / "SKILL.md").write_text(
                "---\n"
                "name: code-review\n"
                "description: Review focused code changes.\n"
                "---\n\n"
                "Check behavior and tests.\n",
                encoding="utf-8",
            )

            skill = SkillStore([root]).load("code-review")

        self.assertEqual(skill.name, "code-review")
        self.assertEqual(skill.instructions, "Check behavior and tests.")

    def test_rejects_a_skill_whose_name_does_not_match_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill_directory = root / "wrong-name"
            skill_directory.mkdir()
            (skill_directory / "SKILL.md").write_text(
                "---\n"
                "name: code-review\n"
                "description: Review code.\n"
                "---\n\n"
                "Review it.\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SkillError, "match its directory"):
                SkillStore([root]).load("wrong-name")


if __name__ == "__main__":
    unittest.main()
