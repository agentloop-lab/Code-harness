import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import main
from agent.loop import AgentLoopError
from agent.model import ModelClientError


class CommandLineTests(unittest.TestCase):
    @patch("main.AgentLoop")
    @patch("main.ModelClient")
    @patch("main.ToolExecutor")
    def test_runs_task_in_selected_workspace(
        self,
        executor_class: Mock,
        model_class: Mock,
        loop_class: Mock,
    ) -> None:
        executor = executor_class.return_value
        executor.definitions = [{"type": "function"}]
        model_class.return_value.config.model_name = "test-model"
        loop = loop_class.return_value
        loop.run.return_value = "Finished."
        loop.messages = []
        output = io.StringIO()

        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch(
                "main.DEFAULT_SESSION_DIRECTORY",
                Path(temporary_directory) / "sessions",
            ):
                exit_code = main.run_cli(
                    [
                        "--workspace",
                        temporary_directory,
                        "Fix the failing test",
                    ],
                    output=output,
                )

            executor_class.assert_called_once_with(Path(temporary_directory).resolve())

        loop_class.assert_called_once_with(
            model_class.return_value,
            tools=executor.definitions,
            tool_executor=unittest.mock.ANY,
            max_steps=10,
            history=[],
        )
        loop.run.assert_called_once_with(
            "Fix the failing test",
            system_prompt=main.SYSTEM_PROMPT,
        )
        self.assertEqual(exit_code, 0)
        displayed = output.getvalue()
        self.assertIn("Code Harness", displayed)
        self.assertIn("Model:     test-model", displayed)
        self.assertIn("You: Fix the failing test", displayed)
        self.assertIn("Agent:\nFinished.", displayed)

    @patch("main.AgentLoop")
    @patch("main.ModelClient")
    @patch("main.ToolExecutor")
    def test_prompts_for_task_when_not_given_as_an_argument(
        self,
        executor_class: Mock,
        model_class: Mock,
        loop_class: Mock,
    ) -> None:
        executor_class.return_value.definitions = []
        loop = loop_class.return_value
        loop.run.side_effect = ["Done.", "Still working."]
        loop.messages = []
        output = io.StringIO()
        inputs = iter(["Create hello.py", "Now run it", "/exit"])

        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch(
                "main.DEFAULT_SESSION_DIRECTORY",
                Path(temporary_directory) / "sessions",
            ):
                exit_code = main.run_cli(
                    ["--workspace", temporary_directory],
                    input_fn=lambda prompt: next(inputs),
                    output=output,
                )

        self.assertEqual(
            loop.run.call_args_list,
            [
                unittest.mock.call(
                    "Create hello.py", system_prompt=main.SYSTEM_PROMPT
                ),
                unittest.mock.call("Now run it", system_prompt=main.SYSTEM_PROMPT),
            ],
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("Session saved.", output.getvalue())

    @patch("main.AgentLoop")
    @patch("main.ModelClient")
    @patch("main.ToolExecutor")
    def test_resume_command_lists_and_switches_session(
        self,
        executor_class: Mock,
        model_class: Mock,
        loop_class: Mock,
    ) -> None:
        executor_class.return_value.definitions = []
        model_class.return_value.config.model_name = "test-model"
        first_loop = Mock(messages=[])
        resumed_loop = Mock(messages=[])
        resumed_loop.run.return_value = "Continued."
        loop_class.side_effect = [first_loop, resumed_loop]
        inputs = iter(["/resume", "1", "Continue the work", "/exit"])
        output = io.StringIO()

        with tempfile.TemporaryDirectory() as temporary_directory:
            session_directory = Path(temporary_directory) / "sessions"
            store = main.SessionStore(session_directory)
            saved = store.create()
            saved.messages = [
                {"role": "user", "content": "Build a calculator"},
                {"role": "assistant", "content": "Created it"},
            ]
            store.save(saved)

            with patch("main.DEFAULT_SESSION_DIRECTORY", session_directory):
                exit_code = main.run_cli(
                    ["--workspace", temporary_directory],
                    input_fn=lambda prompt: next(inputs),
                    output=output,
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(loop_class.call_count, 2)
        self.assertEqual(loop_class.call_args_list[1].kwargs["history"], saved.messages)
        resumed_loop.run.assert_called_once_with(
            "Continue the work", system_prompt=main.SYSTEM_PROMPT
        )
        displayed = output.getvalue()
        self.assertIn("Recent sessions", displayed)
        self.assertIn("Build a calculator", displayed)
        self.assertIn("Resumed: Build a calculator", displayed)

    def test_console_executor_displays_tool_progress(self) -> None:
        executor = Mock(
            return_value={
                "success": True,
                "content": "Updated file: app.py",
                "error_type": None,
            }
        )
        output = io.StringIO()
        visible_executor = main.ConsoleToolExecutor(executor, output)

        result = visible_executor(
            "edit_file",
            {"path": "app.py", "old_text": "old", "new_text": "new"},
        )

        self.assertTrue(result["success"])
        self.assertIn("[1] TOOL  edit_file: app.py", output.getvalue())
        self.assertIn("    OK    Updated file: app.py", output.getvalue())

    def test_console_executor_summarizes_command_result(self) -> None:
        executor = Mock(
            return_value={
                "success": True,
                "content": (
                    '{"command": ["python", "hello.py"], "exit_code": 0, '
                    '"stdout": "Hello!\\n", "stderr": "", "duration": 0.1}'
                ),
                "error_type": None,
            }
        )
        output = io.StringIO()
        visible_executor = main.ConsoleToolExecutor(executor, output)

        visible_executor("run_command", {"command": ["python", "hello.py"]})

        displayed = output.getvalue()
        self.assertIn("[1] TOOL  run_command: python hello.py", displayed)
        self.assertIn("    OUT   Hello!", displayed)
        self.assertIn("    OK    Command exited with code 0.", displayed)
        self.assertNotIn('"duration"', displayed)

    def test_system_prompt_uses_the_active_python_interpreter(self) -> None:
        self.assertIn(sys.executable, main.SYSTEM_PROMPT)
        self.assertIn("Do not use python3", main.SYSTEM_PROMPT)

    @patch("main.AgentLoop")
    @patch("main.ModelClient")
    @patch("main.ToolExecutor")
    def test_displays_model_error_instead_of_generic_loop_error(
        self,
        executor_class: Mock,
        model_class: Mock,
        loop_class: Mock,
    ) -> None:
        executor_class.return_value.definitions = []
        model_error = ModelClientError("Model request timed out.")
        loop_error = AgentLoopError("Agent loop failed.")
        loop_error.__cause__ = model_error
        loop = loop_class.return_value
        loop.run.side_effect = loop_error
        loop.messages = []
        output = io.StringIO()

        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch(
                "main.DEFAULT_SESSION_DIRECTORY",
                Path(temporary_directory) / "sessions",
            ):
                exit_code = main.run_cli(
                    ["--workspace", temporary_directory, "Create hello.py"],
                    output=output,
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("Error: Model request timed out.", output.getvalue())


if __name__ == "__main__":
    unittest.main()
