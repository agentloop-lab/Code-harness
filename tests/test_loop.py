import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call

from agent.loop import AgentLoop, AgentLoopError, AgentLoopLimitError


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

    def test_rejects_invalid_tool_arguments(self) -> None:
        self.model_client.chat.return_value = model_response(
            tool_calls=[tool_call(arguments="not-json")]
        )
        loop = AgentLoop(
            self.model_client,
            tool_executor=self.tool_executor,
        )

        with self.assertRaisesRegex(AgentLoopError, "invalid JSON"):
            loop.run("Inspect a.py")

        self.tool_executor.assert_not_called()
        self.assertEqual(loop.state.task_status, "failed")

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
