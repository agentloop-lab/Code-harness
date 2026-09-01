import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

from agent.loop import (
    AgentLoop,
    AgentLoopError,
    AgentLoopLimitError,
    AgentNoProgressError,
)
from tools.executor import ToolExecutor


def model_response(content=None, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def tool_call(call_id="call-1", name="read_file", arguments='{"path": "a.py"}'):
    function = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(id=call_id, type="function", function=function)


class AgentLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model_client = Mock()
        self.tool_executor = Mock()

    def test_uses_forty_steps_by_default(self) -> None:
        loop = AgentLoop(self.model_client)

        self.assertEqual(loop.max_steps, 40)

    def test_returns_final_answer_without_tool_calls(self) -> None:
        self.model_client.chat.return_value = model_response(content="Done")
        loop = AgentLoop(self.model_client, max_steps=3)

        result = loop.run("Fix the bug", system_prompt="You are a coding agent.")

        self.assertEqual(result, "Done")
        self.model_client.chat.assert_called_once_with(
            [
                {"role": "system", "content": "You are a coding agent."},
                {"role": "user", "content": "Fix the bug"},
            ],
            None,
        )
        self.assertEqual(loop.state.current_step, 1)
        self.assertEqual(loop.state.task_status, "completed")

    def test_keeps_messages_between_turns(self) -> None:
        self.model_client.chat.side_effect = [
            model_response(content="First answer"),
            model_response(content="Second answer"),
        ]
        loop = AgentLoop(self.model_client)

        loop.run("First task", system_prompt="System prompt")
        result = loop.run("Follow-up task", system_prompt="System prompt")

        self.assertEqual(result, "Second answer")
        self.assertEqual(
            self.model_client.chat.call_args_list[1],
            call(
                [
                    {"role": "system", "content": "System prompt"},
                    {"role": "user", "content": "First task"},
                    {"role": "assistant", "content": "First answer"},
                    {"role": "user", "content": "Follow-up task"},
                ],
                None,
            ),
        )

    def test_refreshes_system_prompt_without_losing_summary(self) -> None:
        history = [
            {
                "role": "system",
                "content": "Old prompt\n\nPrevious conversation summary:\nOld progress",
            }
        ]
        self.model_client.chat.return_value = model_response(content="Done")
        loop = AgentLoop(self.model_client, history=history)

        loop.run("Continue", system_prompt="New prompt with memory")

        system_message = self.model_client.chat.call_args.args[0][0]["content"]
        self.assertIn("New prompt with memory", system_message)
        self.assertIn("Old progress", system_message)
        self.assertNotIn("Old prompt", system_message)

    def test_continues_from_saved_history(self) -> None:
        history = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Create app.py"},
            {"role": "assistant", "content": "Created it"},
        ]
        self.model_client.chat.return_value = model_response(content="Updated it")
        loop = AgentLoop(self.model_client, history=history)

        loop.run("Now update it", system_prompt="System prompt")

        sent_messages = self.model_client.chat.call_args.args[0]
        self.assertEqual(sent_messages[:-1], history)
        self.assertEqual(
            sent_messages[-1], {"role": "user", "content": "Now update it"}
        )

    def test_executes_tool_and_returns_observation_to_model(self) -> None:
        tools = [{"type": "function", "function": {"name": "read_file"}}]
        first_response = model_response(tool_calls=[tool_call()])
        final_response = model_response(content="Fixed")
        self.model_client.chat.side_effect = [first_response, final_response]
        self.tool_executor.return_value = {"content": "print('hello')"}
        loop = AgentLoop(
            self.model_client,
            tools=tools,
            tool_executor=self.tool_executor,
            max_steps=3,
        )

        result = loop.run("Inspect a.py")

        self.assertEqual(result, "Fixed")
        self.tool_executor.assert_called_once_with("read_file", {"path": "a.py"})
        expected_messages = [
            {"role": "user", "content": "Inspect a.py"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path": "a.py"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call-1",
                "content": '{"content": "print(\'hello\')"}',
            },
        ]
        self.assertEqual(
            self.model_client.chat.call_args_list,
            [
                call([{"role": "user", "content": "Inspect a.py"}], tools),
                call(expected_messages, tools),
            ],
        )
        self.assertEqual(loop.state.current_step, 2)
        self.assertEqual(len(loop.state.tool_calls), 1)
        self.assertEqual(loop.state.task_status, "completed")

    def test_processes_tool_results_with_context_manager(self) -> None:
        self.model_client.chat.side_effect = [
            model_response(tool_calls=[tool_call()]),
            model_response(content="Done"),
        ]
        self.tool_executor.return_value = "large output"
        context_manager = Mock()
        context_manager.prepare_context.side_effect = (
            lambda messages, model_client: (list(messages), False)
        )
        context_manager.process_tool_result.return_value = "stored preview"
        loop = AgentLoop(
            self.model_client,
            tool_executor=self.tool_executor,
            context_manager=context_manager,
        )

        loop.run("Inspect a.py")

        context_manager.process_tool_result.assert_called_once_with("large output")
        self.assertEqual(context_manager.prepare_context.call_count, 2)
        self.assertEqual(loop.messages[2]["content"], "stored preview")

    def test_replaces_history_after_automatic_compaction(self) -> None:
        self.model_client.chat.return_value = model_response(content="Done")
        context_manager = Mock()
        summary = [{"role": "system", "content": "Conversation summary"}]
        context_manager.prepare_context.return_value = (summary, True)
        loop = AgentLoop(
            self.model_client,
            history=[{"role": "user", "content": "Old task"}],
            context_manager=context_manager,
        )

        loop.run("Continue")

        self.assertEqual(
            loop.messages,
            [
                {"role": "system", "content": "Conversation summary"},
                {"role": "assistant", "content": "Done"},
            ],
        )

    def test_returns_invalid_arguments_to_model(self) -> None:
        self.model_client.chat.side_effect = [
            model_response(tool_calls=[tool_call(arguments="not-json")]),
            model_response(content="Recovered"),
        ]
        loop = AgentLoop(
            self.model_client,
            tool_executor=self.tool_executor,
        )

        result = loop.run("Inspect a.py")
        tool_result = json.loads(loop.state.messages[2]["content"])

        self.assertEqual(result, "Recovered")
        self.assertEqual(tool_result["error_type"], "InvalidArguments")
        self.tool_executor.assert_not_called()
        self.assertEqual(loop.state.task_status, "completed")

    def test_returns_tool_execution_error_to_model(self) -> None:
        self.model_client.chat.side_effect = [
            model_response(tool_calls=[tool_call()]),
            model_response(content="Recovered"),
        ]
        self.tool_executor.side_effect = RuntimeError("tool failed")
        loop = AgentLoop(
            self.model_client,
            tool_executor=self.tool_executor,
        )

        result = loop.run("Inspect a.py")
        tool_result = json.loads(loop.state.messages[2]["content"])

        self.assertEqual(result, "Recovered")
        self.assertEqual(tool_result["error_type"], "ToolError")
        self.assertEqual(loop.state.task_status, "completed")

    def test_requires_successful_command_after_file_change(self) -> None:
        self.model_client.chat.side_effect = [
            model_response(
                tool_calls=[
                    tool_call(
                        name="write_file",
                        arguments='{"path": "new.py", "content": "pass\\n"}',
                    )
                ]
            ),
            model_response(content="Implemented."),
            model_response(
                tool_calls=[
                    tool_call(
                        call_id="call-2",
                        name="run_command",
                        arguments='{"command": ["python", "-B", "-m", "unittest"]}',
                    )
                ]
            ),
            model_response(content="Implemented and verified."),
        ]
        self.tool_executor.side_effect = [
            {"success": True, "content": "Created file: new.py"},
            {"success": True, "content": '{"exit_code": 0}'},
        ]
        loop = AgentLoop(
            self.model_client,
            tool_executor=self.tool_executor,
            max_steps=5,
        )

        result = loop.run("Create new.py")

        self.assertEqual(result, "Implemented and verified.")
        self.assertEqual(loop.state.verification_reminders, 1)
        self.assertFalse(loop.state.verification_required)
        self.assertTrue(loop.state.last_verification_successful)
        self.assertIn(
            "workspace has changed",
            loop.messages[4]["content"],
        )

    def test_verification_state_uses_real_file_and_command_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            executor = ToolExecutor(workspace)
            self.model_client.chat.side_effect = [
                model_response(
                    tool_calls=[
                        tool_call(
                            name="write_file",
                            arguments=(
                                '{"path": "check.py", '
                                '"content": "print(\\\"verified\\\")\\n"}'
                            ),
                        )
                    ]
                ),
                model_response(content="Created."),
                model_response(
                    tool_calls=[
                        tool_call(
                            call_id="call-2",
                            name="run_command",
                            arguments=json.dumps(
                                {"command": [sys.executable, "-B", "check.py"]}
                            ),
                        )
                    ]
                ),
                model_response(content="Created and verified."),
            ]
            loop = AgentLoop(
                self.model_client,
                tools=executor.definitions,
                tool_executor=executor,
                max_steps=5,
            )

            result = loop.run("Create and verify check.py")

            self.assertEqual(result, "Created and verified.")
            self.assertEqual(
                (workspace / "check.py").read_text(encoding="utf-8"),
                'print("verified")\n',
            )
            self.assertFalse(loop.state.verification_required)
            self.assertTrue(loop.state.last_verification_successful)

    def test_failed_command_does_not_verify_file_change(self) -> None:
        self.model_client.chat.side_effect = [
            model_response(
                tool_calls=[
                    tool_call(
                        name="edit_file",
                        arguments=(
                            '{"path": "app.py", "old_text": "old", '
                            '"new_text": "new"}'
                        ),
                    )
                ]
            ),
            model_response(
                tool_calls=[
                    tool_call(
                        call_id="call-2",
                        name="run_command",
                        arguments='{"command": ["python", "-B", "-m", "unittest"]}',
                    )
                ]
            ),
            model_response(content="Done."),
            model_response(content="Verification unavailable: tests are broken."),
        ]
        self.tool_executor.side_effect = [
            {"success": True, "content": "Updated file: app.py"},
            {"success": False, "content": "failed", "error_type": "CommandFailed"},
        ]
        loop = AgentLoop(
            self.model_client,
            tool_executor=self.tool_executor,
            max_steps=5,
        )

        result = loop.run("Update app.py")

        self.assertEqual(result, "Verification unavailable: tests are broken.")
        self.assertEqual(loop.state.verification_reminders, 1)
        self.assertFalse(loop.state.last_verification_successful)
        self.assertFalse(loop.state.verification_required)

    def test_warns_after_repeated_tool_observations(self) -> None:
        self.model_client.chat.side_effect = [
            model_response(tool_calls=[tool_call(call_id="call-1")]),
            model_response(tool_calls=[tool_call(call_id="call-2")]),
            model_response(
                tool_calls=[
                    tool_call(
                        call_id="call-3",
                        name="search_text",
                        arguments='{"query": "target"}',
                    )
                ]
            ),
            model_response(content="Found another approach."),
        ]
        self.tool_executor.side_effect = [
            {"success": True, "content": "same file"},
            {"success": True, "content": "same file"},
            {"success": True, "content": "new result"},
        ]
        loop = AgentLoop(
            self.model_client,
            tool_executor=self.tool_executor,
            max_steps=5,
        )

        result = loop.run("Inspect the project")

        self.assertEqual(result, "Found another approach.")
        self.assertEqual(loop.state.no_progress_warnings, 1)
        warnings = [
            message
            for message in loop.messages
            if message.get("role") == "user"
            and "No progress detected" in str(message.get("content"))
        ]
        self.assertEqual(len(warnings), 1)

    def test_stops_after_repeated_tool_observations_continue(self) -> None:
        self.model_client.chat.return_value = model_response(tool_calls=[tool_call()])
        self.tool_executor.return_value = {
            "success": False,
            "content": "missing",
            "error_type": "FileNotFound",
        }
        loop = AgentLoop(
            self.model_client,
            tool_executor=self.tool_executor,
            max_steps=6,
        )

        with self.assertRaisesRegex(AgentNoProgressError, "repeated 3 times"):
            loop.run("Inspect a.py")

        self.assertEqual(self.model_client.chat.call_count, 3)
        self.assertEqual(self.tool_executor.call_count, 3)
        self.assertEqual(loop.state.no_progress_warnings, 1)
        self.assertEqual(loop.state.task_status, "no_progress")

    def test_marks_model_errors_as_failed(self) -> None:
        self.model_client.chat.side_effect = RuntimeError("network")
        loop = AgentLoop(self.model_client)

        with self.assertRaises(AgentLoopError) as context:
            loop.run("Inspect a.py")

        self.assertIsInstance(context.exception.__cause__, RuntimeError)
        self.assertEqual(loop.state.current_step, 1)
        self.assertEqual(loop.state.task_status, "failed")

    def test_stops_at_max_steps(self) -> None:
        self.model_client.chat.return_value = model_response(tool_calls=[tool_call()])
        self.tool_executor.return_value = "file content"
        loop = AgentLoop(
            self.model_client,
            tool_executor=self.tool_executor,
            max_steps=2,
        )

        with self.assertRaisesRegex(AgentLoopLimitError, "maximum of 2 steps"):
            loop.run("Inspect a.py")

        self.assertEqual(self.model_client.chat.call_count, 2)
        self.assertEqual(self.tool_executor.call_count, 2)
        self.assertEqual(loop.state.current_step, 2)
        self.assertEqual(loop.state.task_status, "max_steps")

    def test_rejects_non_positive_step_limit(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 1"):
            AgentLoop(self.model_client, max_steps=0)


if __name__ == "__main__":
    unittest.main()
