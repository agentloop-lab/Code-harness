"""Basic agent loop orchestration."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping, Sequence

from agent.model import ModelClient


TaskStatus = Literal["running", "completed", "max_steps", "failed"]
ToolExecutor = Callable[[str, Mapping[str, Any]], Any]


class AgentLoopError(RuntimeError):
    """Raised when the agent loop cannot continue."""


class AgentLoopLimitError(AgentLoopError):
    """Raised when the agent reaches its step limit."""


@dataclass
class AgentState:
    """Mutable state for one agent run."""

    messages: list[dict[str, Any]]
    max_steps: int
    current_step: int = 0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    task_status: TaskStatus = "running"


class AgentLoop:
    """Run model and tool calls until the model returns a final answer."""

    def __init__(
        self,
        model_client: ModelClient,
        tools: Sequence[Mapping[str, Any]] | None = None,
        tool_executor: ToolExecutor | None = None,
        max_steps: int = 10,
        history: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1.")

        self.model_client = model_client
        self.tools = list(tools) if tools else None
        self.tool_executor = tool_executor
        self.max_steps = max_steps
        self.messages = [dict(message) for message in history or []]
        self.state: AgentState | None = None

    def run(self, task: str, system_prompt: str | None = None) -> str:
        if not self.messages and system_prompt:
            self.messages.append({"role": "system", "content": system_prompt})
        self.messages.append({"role": "user", "content": task})

        self.state = AgentState(messages=self.messages, max_steps=self.max_steps)

        while self.state.current_step < self.state.max_steps:
            self.state.current_step += 1
            try:
                response = self.model_client.chat(
                    list(self.state.messages), self.tools
                )
                message = self._response_message(response)
                assistant_message, tool_calls = self._assistant_message(message)
                self.state.messages.append(assistant_message)

                if not tool_calls:
                    self.state.task_status = "completed"
                    return assistant_message.get("content") or ""

                self.state.tool_calls.extend(tool_calls)
                for tool_call in tool_calls:
                    self.state.messages.append(self._execute_tool(tool_call))
            except AgentLoopError:
                self.state.task_status = "failed"
                raise
            except Exception as exc:
                self.state.task_status = "failed"
                raise AgentLoopError("Agent loop failed.") from exc

        self.state.task_status = "max_steps"
        raise AgentLoopLimitError(
            f"Agent reached the maximum of {self.state.max_steps} steps."
        )

    @staticmethod
    def _response_message(response: Any) -> Any:
        choices = getattr(response, "choices", None)
        if not choices:
            raise AgentLoopError("Model response does not contain any choices.")

        message = getattr(choices[0], "message", None)
        if message is None:
            raise AgentLoopError("Model response does not contain a message.")
        return message

    def _assistant_message(
        self, message: Any
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        content = self._field(message, "content")
        raw_tool_calls = self._field(message, "tool_calls") or []
        tool_calls = [self._tool_call_to_dict(call) for call in raw_tool_calls]

        result: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            result["tool_calls"] = tool_calls
        return result, tool_calls

    def _execute_tool(self, tool_call: Mapping[str, Any]) -> dict[str, Any]:
        function = tool_call["function"]
        name = function["name"]
        raw_arguments = function["arguments"]
        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError:
            return self._tool_error_message(
                tool_call["id"],
                "InvalidArguments",
                f"Tool '{name}' arguments are not valid JSON.",
            )

        if not isinstance(arguments, dict):
            return self._tool_error_message(
                tool_call["id"],
                "InvalidArguments",
                f"Tool '{name}' arguments must be a JSON object.",
            )

        if self.tool_executor is None:
            return self._tool_error_message(
                tool_call["id"],
                "ToolUnavailable",
                "No tool executor is available.",
            )

        try:
            result = self.tool_executor(name, arguments)
        except Exception:
            return self._tool_error_message(
                tool_call["id"],
                "ToolError",
                f"Tool execution failed: {name}",
            )

        try:
            content = (
                result
                if isinstance(result, str)
                else json.dumps(result, ensure_ascii=False)
            )
        except (TypeError, ValueError):
            return self._tool_error_message(
                tool_call["id"],
                "ToolError",
                f"Tool returned an invalid result: {name}",
            )
        return {
            "role": "tool",
            "tool_call_id": tool_call["id"],
            "content": content,
        }

    @staticmethod
    def _tool_error_message(
        tool_call_id: str,
        error_type: str,
        message: str,
    ) -> dict[str, Any]:
        content = json.dumps(
            {
                "success": False,
                "content": message,
                "error_type": error_type,
            },
            ensure_ascii=False,
        )
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content,
        }

    @classmethod
    def _tool_call_to_dict(cls, tool_call: Any) -> dict[str, Any]:
        call_id = cls._field(tool_call, "id")
        call_type = cls._field(tool_call, "type") or "function"
        function = cls._field(tool_call, "function")
        name = cls._field(function, "name")
        arguments = cls._field(function, "arguments")

        if not call_id or not name or arguments is None:
            raise AgentLoopError("Model returned an incomplete tool call.")
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments, ensure_ascii=False)

        return {
            "id": call_id,
            "type": call_type,
            "function": {"name": name, "arguments": arguments},
        }

    @staticmethod
    def _field(value: Any, name: str) -> Any:
        if isinstance(value, Mapping):
            return value.get(name)
        return getattr(value, name, None)
