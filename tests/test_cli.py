import asyncio
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from prompt_toolkit.document import Document
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output.vt100 import Vt100_Output

import main
from agent.loop import AgentLoopError
from agent.model import ModelClientError


class CommandLineTests(unittest.TestCase):
    def test_completes_slash_command_prefixes(self) -> None:
        completer = main.SlashCommandCompleter()

        status_matches = list(
            completer.get_completions(Document("/st"), Mock())
        )
        task_matches = list(
            completer.get_completions(Document("create file"), Mock())
        )

        self.assertEqual(
            [completion.text for completion in status_matches],
            ["/status"],
        )
        self.assertEqual(task_matches, [])

    def test_completes_open_directory(self) -> None:
        completer = main.SlashCommandCompleter()
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "project-one").mkdir()
            document = Document(f"/open {root / 'pro'}")

            matches = list(completer.get_completions(document, Mock()))

        self.assertIn("ject-one", [completion.text for completion in matches])

    def test_completes_workspace_file_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            source = workspace / "src"
            source.mkdir()
            (source / "main.py").write_text("print('hello')\n", encoding="utf-8")
            completer = main.SlashCommandCompleter(lambda: workspace)

            matches = list(
                completer.get_completions(
                    Document("Review @src/ma"),
                    Mock(),
                )
            )

        self.assertIn("in.py", [completion.text for completion in matches])

    def test_renders_and_selects_slash_commands(self) -> None:
        async def run_prompt(history_file: Path) -> tuple[str, str, str]:
            capture = io.StringIO()
            terminal_output = Vt100_Output(
                capture,
                get_size=lambda: Size(rows=24, columns=120),
                enable_cpr=False,
            )
            with create_pipe_input() as pipe:
                session = main._task_prompt_session(
                    history_file,
                    prompt_input=pipe,
                    prompt_output=terminal_output,
                )
                prompt = asyncio.create_task(session.prompt_async("Task> "))
                await asyncio.sleep(0.05)
                pipe.send_text("/")
                for _ in range(100):
                    if "/workspace" in capture.getvalue():
                        break
                    await asyncio.sleep(0.01)
                rendered = capture.getvalue()
                pipe.send_text("\x1b[B")
                await asyncio.sleep(0.05)
                pipe.send_text("\r")
                selected = await prompt
                second_prompt = asyncio.create_task(session.prompt_async("Task> "))
                await asyncio.sleep(0.05)
                pipe.send_text("\x1b[A")
                await asyncio.sleep(0.05)
                pipe.send_text("\r")
                recalled = await second_prompt
            return rendered, selected, recalled

        with tempfile.TemporaryDirectory() as temporary_directory:
            rendered, selected, recalled = asyncio.run(
                run_prompt(Path(temporary_directory) / "history")
            )

        self.assertIn("/workspace", rendered)
        self.assertEqual(selected, "/workspace")
        self.assertEqual(recalled, "/workspace")

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
            context_manager=unittest.mock.ANY,
        )
        loop.run.assert_called_once_with(
            "Fix the failing test",
            system_prompt=main.SYSTEM_PROMPT,
        )
        self.assertEqual(exit_code, 0)
        displayed = output.getvalue()
        self.assertIn("Code Harness | test-model", displayed)
        self.assertIn("Task> Fix the failing test", displayed)
        self.assertIn("Agent>\nFinished.", displayed)

    @patch("main.AgentLoop")
    @patch("main.ModelClient")
    @patch("main.ToolExecutor")
    def test_attaches_referenced_file_to_task(
        self,
        executor_class: Mock,
        model_class: Mock,
        loop_class: Mock,
    ) -> None:
        executor_class.return_value.definitions = []
        model_class.return_value.config.model_name = "test-model"
        loop = loop_class.return_value
        loop.messages = []
        loop.run.return_value = "Reviewed."
        output = io.StringIO()

        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            (workspace / "notes.txt").write_text(
                "important context\n",
                encoding="utf-8",
            )
            with patch(
                "main.DEFAULT_SESSION_DIRECTORY",
                workspace / "sessions",
            ):
                exit_code = main.run_cli(
                    [
                        "--workspace",
                        temporary_directory,
                        "Review",
                        "@notes.txt",
                    ],
                    output=output,
                )

        prompt = loop.run.call_args.args[0]
        self.assertEqual(exit_code, 0)
        self.assertIn("Review @notes.txt", prompt)
        self.assertIn("[Referenced file: notes.txt]\nimportant context", prompt)
        self.assertIn("[context] Attached 1 file(s).", output.getvalue())

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
            saved = store.create(Path(temporary_directory))
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

    @patch("main.ContextManager")
    @patch("main.AgentLoop")
    @patch("main.ModelClient")
    @patch("main.ToolExecutor")
    def test_compact_command_replaces_and_saves_history(
        self,
        executor_class: Mock,
        model_class: Mock,
        loop_class: Mock,
        context_class: Mock,
    ) -> None:
        executor_class.return_value.definitions = []
        model_class.return_value.config.model_name = "test-model"
        loop = loop_class.return_value
        loop.messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Build a calculator"},
            {"role": "assistant", "content": "Created it"},
        ]
        loop.run.return_value = "Done."
        compacted = [{"role": "system", "content": "Conversation summary"}]
        manager = context_class.return_value
        manager.compact_history.return_value = compacted
        manager.estimate_size.side_effect = [500, 100]
        inputs = iter(["Continue the task", "/compact", "/exit"])
        output = io.StringIO()

        with tempfile.TemporaryDirectory() as temporary_directory:
            session_directory = Path(temporary_directory) / "sessions"
            with patch("main.DEFAULT_SESSION_DIRECTORY", session_directory):
                exit_code = main.run_cli(
                    ["--workspace", temporary_directory],
                    input_fn=lambda prompt: next(inputs),
                    output=output,
                )

            saved = main.SessionStore(session_directory).list_recent()[0]

        self.assertEqual(exit_code, 0)
        manager.compact_history.assert_called_once()
        self.assertEqual(loop.messages, compacted)
        self.assertEqual(saved.messages, compacted)
        self.assertEqual(saved.display_title, "Build a calculator")
        self.assertEqual(saved.turn_count, 1)
        self.assertIn("Compacted context: 500 -> 100 characters.", output.getvalue())

    @patch("main.AgentLoop")
    @patch("main.ModelClient")
    @patch("main.ToolExecutor")
    def test_memory_commands_persist_and_inject_note(
        self,
        executor_class: Mock,
        model_class: Mock,
        loop_class: Mock,
    ) -> None:
        executor_class.return_value.definitions = []
        model_class.return_value.config.model_name = "test-model"
        loop = loop_class.return_value
        loop.messages = []
        loop.run.return_value = "Done."
        inputs = iter(
            [
                "/remember Use pytest for tests.",
                "/memory",
                "Continue the task",
                "/exit",
            ]
        )
        output = io.StringIO()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with (
                patch("main.DEFAULT_SESSION_DIRECTORY", root / "sessions"),
                patch("main.DEFAULT_PROJECT_DIRECTORY", root / "projects"),
            ):
                memory_file = main._memory_file_for_workspace(root)
                exit_code = main.run_cli(
                    ["--workspace", temporary_directory],
                    input_fn=lambda prompt: next(inputs),
                    output=output,
                )
            notes = main.ProjectMemoryStore(memory_file).items()

        self.assertEqual(exit_code, 0)
        self.assertEqual(notes, ["Use pytest for tests."])
        prompt = loop.run.call_args.kwargs["system_prompt"]
        self.assertIn("Project memory:\n- Use pytest for tests.", prompt)
        displayed = output.getvalue()
        self.assertIn("Project memory updated.", displayed)
        self.assertIn("  - Use pytest for tests.", displayed)

    @patch("main.AgentLoop")
    @patch("main.ModelClient")
    @patch("main.ToolExecutor")
    def test_open_switches_workspace_and_resets_status(
        self,
        executor_class: Mock,
        model_class: Mock,
        loop_class: Mock,
    ) -> None:
        executor_class.return_value.definitions = []
        model_class.return_value.config.model_name = "test-model"
        first_loop = Mock(messages=[{"role": "user", "content": "First task"}])
        first_loop.run.return_value = "Done."
        second_loop = Mock(messages=[])
        loop_class.side_effect = [first_loop, second_loop]
        output = io.StringIO()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first_workspace = root / "first"
            second_workspace = root / "second"
            first_workspace.mkdir()
            second_workspace.mkdir()
            inputs = iter(
                [
                    "/remember First workspace note.",
                    "First task",
                    f"/open {root / 'missing'}",
                    f"/open {second_workspace}",
                    "/workspace",
                    "/memory",
                    "/status",
                    "/exit",
                ]
            )
            with (
                patch("main.DEFAULT_SESSION_DIRECTORY", root / "sessions"),
                patch("main.DEFAULT_PROJECT_DIRECTORY", root / "projects"),
            ):
                exit_code = main.run_cli(
                    ["--workspace", str(first_workspace)],
                    input_fn=lambda prompt: next(inputs),
                    output=output,
                )
            first_sessions = main.SessionStore(root / "sessions").list_recent(
                workspace=first_workspace
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            executor_class.call_args_list,
            [
                unittest.mock.call(first_workspace.resolve()),
                unittest.mock.call(second_workspace.resolve()),
            ],
        )
        self.assertEqual(len(first_sessions), 1)
        displayed = output.getvalue()
        self.assertIn("Workspace does not exist:", displayed)
        self.assertIn(f"Workspace: {second_workspace.resolve()}", displayed)
        self.assertIn("Project memory is empty.", displayed)
        self.assertIn("No task changes to show yet.", displayed)

    def test_workspace_memory_paths_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with patch("main.DEFAULT_PROJECT_DIRECTORY", root / "state"):
                first = main._memory_file_for_workspace(root / "first")
                second = main._memory_file_for_workspace(root / "second")

        self.assertNotEqual(first, second)
        self.assertEqual(first.parent.parent, root / "state")
        self.assertEqual(second.parent.parent, root / "state")

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
        self.assertEqual(
            output.getvalue().strip(),
            "[1] OK    edit_file app.py | Updated file: app.py",
        )

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
        self.assertIn("[1] OK    run_command python hello.py | exit 0 | 0.10s", displayed)
        self.assertNotIn("Hello!", displayed)

    def test_verbose_console_executor_displays_command_output(self) -> None:
        executor = Mock(
            return_value={
                "success": False,
                "content": (
                    '{"command": ["python", "hello.py"], "exit_code": 1, '
                    '"stdout": "starting\\n", "stderr": "line 1\\nSyntaxError", '
                    '"duration": 0.2}'
                ),
                "error_type": "command_failed",
            }
        )
        output = io.StringIO()
        settings = main.ConsoleSettings(verbose=True)
        visible_executor = main.ConsoleToolExecutor(executor, output, settings)

        visible_executor("run_command", {"command": ["python", "hello.py"]})

        displayed = output.getvalue()
        self.assertIn("FAIL  run_command python hello.py | exit 1", displayed)
        self.assertIn("| SyntaxError", displayed)
        self.assertIn("    OUT   starting", displayed)
        self.assertIn("    ERR   line 1\n    ERR   SyntaxError", displayed)

    @patch("main.AgentLoop")
    @patch("main.ModelClient")
    @patch("main.ToolExecutor")
    def test_verbose_status_and_diff_commands(
        self,
        executor_class: Mock,
        model_class: Mock,
        loop_class: Mock,
    ) -> None:
        executor_class.return_value.definitions = []
        model_class.return_value.config.model_name = "test-model"
        loop = loop_class.return_value
        loop.messages = []
        output = io.StringIO()

        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)

            def create_file(*args: object, **kwargs: object) -> str:
                (workspace / "hello.py").write_text(
                    'print("hello")\n', encoding="utf-8"
                )
                return "Done."

            loop.run.side_effect = create_file
            inputs = iter(
                ["/verbose", "Create hello.py", "/status", "/diff", "/exit"]
            )
            with patch(
                "main.DEFAULT_SESSION_DIRECTORY",
                workspace / "sessions",
            ):
                exit_code = main.run_cli(
                    ["--workspace", temporary_directory],
                    input_fn=lambda prompt: next(inputs),
                    output=output,
                )

        self.assertEqual(exit_code, 0)
        displayed = output.getvalue()
        self.assertIn("Verbose tool output: on.", displayed)
        self.assertIn("  A hello.py", displayed)
        self.assertIn("--- /dev/null", displayed)
        self.assertIn("+++ b/hello.py", displayed)
        self.assertIn('+print("hello")', displayed)

    @patch("main.AgentLoop")
    @patch("main.ModelClient")
    @patch("main.ToolExecutor")
    def test_help_lists_commands_and_rejects_unknown_command(
        self,
        executor_class: Mock,
        model_class: Mock,
        loop_class: Mock,
    ) -> None:
        executor_class.return_value.definitions = []
        model_class.return_value.config.model_name = "test-model"
        loop_class.return_value.messages = []
        inputs = iter(["/help", "/unknown", "/exit"])
        output = io.StringIO()

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

        self.assertEqual(exit_code, 0)
        displayed = output.getvalue()
        self.assertIn("Available commands", displayed)
        self.assertIn("/remember <note>", displayed)
        self.assertIn("Unknown command. Type /help", displayed)
        loop_class.return_value.run.assert_not_called()

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
