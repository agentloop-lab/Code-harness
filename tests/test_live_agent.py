"""Opt-in integration test that calls the configured model API."""

from __future__ import annotations

import os
import unittest
from typing import Any, Mapping

from agent.loop import AgentLoop
from agent.model import ModelClient


RUN_LIVE_TESTS = os.getenv("RUN_LIVE_TESTS") == "1"


@unittest.skipUnless(RUN_LIVE_TESTS, "set RUN_LIVE_TESTS=1 to call the real API")
class LiveAgentTests(unittest.TestCase):
    def test_model_calls_local_add_tool(self) -> None:
        calls: list[tuple[str, Mapping[str, Any]]] = []

        def execute_tool(name: str, arguments: Mapping[str, Any]) -> dict[str, int]:
            calls.append((name, arguments))
            if name != "add_numbers":
                raise ValueError(f"Unexpected tool: {name}")
            return {"result": int(arguments["a"]) + int(arguments["b"])}

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "add_numbers",
                    "description": "Add two integers and return their sum.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "a": {"type": "integer"},
                            "b": {"type": "integer"},
                        },
                        "required": ["a", "b"],
                        "additionalProperties": False,
                    },
                },
            }
        ]
        loop = AgentLoop(
            ModelClient(),
            tools=tools,
            tool_executor=execute_tool,
            max_steps=3,
        )

        result = loop.run(
            "Use add_numbers to calculate 17 + 25. After the tool result, "
            "reply with exactly: 42",
            system_prompt="Always use the provided tool for arithmetic.",
        )

        self.assertEqual(result.strip(), "42")
        self.assertEqual(calls, [("add_numbers", {"a": 17, "b": 25})])
        self.assertEqual(loop.state.task_status, "completed")
        self.assertEqual(loop.state.current_step, 2)
        self.assertEqual(len(loop.state.tool_calls), 1)


if __name__ == "__main__":
    unittest.main()
