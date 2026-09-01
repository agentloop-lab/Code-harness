"""Basic agent loop orchestration."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping, Sequence

from agent.context import ContextManager, SUMMARY_MARKER
from agent.model import ModelClient


TaskStatus = Literal[
    "running",
    "completed",
    "max_steps",
    "no_progress",
    "failed",
]
ToolExecutor = Callable[[str, Mapping[str, Any]], Any]
DEFAULT_MAX_STEPS = 40
MODIFYING_TOOL_NAMES = frozenset({"write_file", "edit_file"})
VERIFICATION_TOOL_NAME = "run_command"
VERIFICATION_UNAVAILABLE_PREFIX = "verification unavailable:"
VERIFICATION_REMINDER = (
    "The workspace has changed, but no successful command has verified the "
    "latest file changes. Run an appropriate test, build, lint, or validation "
    "command before finishing. If verification genuinely cannot be run, begin "
    "the final answer with 'Verification unavailable:' and explain why."
)
NO_PROGRESS_WARNING = (
    "No progress detected: the same tool call produced the same observation "
    "again. Do not repeat it. Inspect different evidence, change the arguments, "
    "or use another approach."
)


class AgentLoopError(RuntimeError):
    """Raised when the agent loop cannot continue."""


class AgentLoopLimitError(AgentLoopError):
    """Raised when the agent reaches its step limit."""


class AgentNoProgressError(AgentLoopError):
    """Raised when repeated tool calls produce no new information."""


@dataclass
class AgentState:
    """Mutable state for one agent run."""

    messages: list[dict[str, Any]]
    max_steps: int
    current_step: int = 0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    task_status: TaskStatus = "running"
    workspace_dirty: bool = False
    verification_required: bool = False
    last_verification_successful: bool = False
    verification_reminders: int = 0
    no_progress_warnings: int = 0
    repeated_observations: int = 0


class AgentLoop:
    """Run model and tool calls until the model returns a final answer."""

    def __init__(
        self,
        model_client: ModelClient,
        tools: Sequence[Mapping[str, Any]] | None = None,
        tool_executor: ToolExecutor | None = None,
        max_steps: int = DEFAULT_MAX_STEPS,
        history: Sequence[Mapping[str, Any]] | None = None,
        context_manager: ContextManager | None = None,
        no_progress_warning_threshold: int = 2,
        no_progress_stop_threshold: int = 3,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1.")
        if no_progress_warning_threshold < 2:
            raise ValueError("no_progress_warning_threshold must be at least 2.")
        if no_progress_stop_threshold <= no_progress_warning_threshold:
            raise ValueError(
                "no_progress_stop_threshold must exceed the warning threshold."
            )

        self.model_client = model_client
        self.tools = list(tools) if tools else None
        self.tool_executor = tool_executor
        self.max_steps = max_steps
        self.messages = [dict(message) for message in history or []]
        self.context_manager = context_manager
        self.no_progress_warning_threshold = no_progress_warning_threshold
        self.no_progress_stop_threshold = no_progress_stop_threshold
        self.workspace_dirty = False
        self.verification_required = False
        self.last_verification_successful = False
        self._last_observation: str | None = None
        self._last_warned_observation: str | None = None
        self._repeated_observations = 0
        self.state: AgentState | None = None

    def run(self, task: str, system_prompt: str | None = None) -> str:
        if system_prompt:
            self._set_system_prompt(system_prompt)
        self.messages.append({"role": "user", "content": task})
        self._last_observation = None
        self._last_warned_observation = None
        self._repeated_observations = 0

        self.state = AgentState(
            messages=self.messages,
            max_steps=self.max_steps,
            workspace_dirty=self.workspace_dirty,
            verification_required=self.verification_required,
            last_verification_successful=self.last_verification_successful,
        )

        while self.state.current_step < self.state.max_steps:
            self.state.current_step += 1
            try:
                context = (
                    self.context_manager.prepare_context(
                        self.state.messages,
                        self.model_client,
                    )
                    if self.context_manager is not None
                    else (list(self.state.messages), False)
                )
                request_messages, was_compacted = context
                if was_compacted:
                    self.state.messages[:] = request_messages
                response = self.model_client.chat(
                    request_messages, self.tools
                )
                message = self._response_message(response)
                assistant_message, tool_calls = self._assistant_message(message)
                self.state.messages.append(assistant_message)

                if not tool_calls:
                    content = assistant_message.get("content") or ""
                    if self.verification_required:
                        if self._reports_verification_unavailable(content):
                            self.verification_required = False
                            self.last_verification_successful = False
                            self._sync_verification_state()
                        else:
                            self.state.verification_reminders += 1
                            self.state.messages.append(
                                {"role": "user", "content": VERIFICATION_REMINDER}
                            )
                            continue
                    self.state.task_status = "completed"
                    return content

                self.state.tool_calls.extend(tool_calls)
                for tool_call in tool_calls:
                    tool_message = self._execute_tool(tool_call)
                    self.state.messages.append(tool_message)
                    self._observe_tool_result(tool_call, tool_message)
                self._handle_no_progress()
            except AgentNoProgressError:
                self.state.task_status = "no_progress"
                raise
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

    def _set_system_prompt(self, system_prompt: str) -> None:
        if not self.messages or self.messages[0].get("role") != "system":
            self.messages.insert(0, {"role": "system", "content": system_prompt})
            return

        current = self.messages[0].get("content")
        summary = ""
        if isinstance(current, str) and SUMMARY_MARKER in current:
            summary = SUMMARY_MARKER + current.split(SUMMARY_MARKER, 1)[1]
        self.messages[0] = {
            "role": "system",
            "content": f"{system_prompt}{summary}",
        }

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

        self._record_verification_result(name, result)

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
        if self.context_manager is not None:
            content = self.context_manager.process_tool_result(content)
        return {
            "role": "tool",
            "tool_call_id": tool_call["id"],
            "content": content,
        }

    def _record_verification_result(self, name: str, result: Any) -> None:
        if not isinstance(result, Mapping) or result.get("success") is not True:
            return
        if name in MODIFYING_TOOL_NAMES:
            self.workspace_dirty = True
            self.verification_required = True
            self.last_verification_successful = False
        elif name == VERIFICATION_TOOL_NAME and self.verification_required:
            self.verification_required = False
            self.last_verification_successful = True
        self._sync_verification_state()

    def _sync_verification_state(self) -> None:
        if self.state is None:
            return
        self.state.workspace_dirty = self.workspace_dirty
        self.state.verification_required = self.verification_required
        self.state.last_verification_successful = (
            self.last_verification_successful
        )

    @staticmethod
    def _reports_verification_unavailable(content: str) -> bool:
        return content.lstrip().casefold().startswith(
            VERIFICATION_UNAVAILABLE_PREFIX
        )

    def _observe_tool_result(
        self,
        tool_call: Mapping[str, Any],
        tool_message: Mapping[str, Any],
    ) -> None:
        function = tool_call.get("function")
        name = function.get("name") if isinstance(function, Mapping) else None
        arguments = (
            function.get("arguments") if isinstance(function, Mapping) else None
        )
        try:
            parsed_arguments = (
                json.loads(arguments)
                if isinstance(arguments, str)
                else arguments
            )
        except json.JSONDecodeError:
            parsed_arguments = arguments
        observation = json.dumps(
            {
                "name": name,
                "arguments": parsed_arguments,
                "content": tool_message.get("content"),
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        if observation == self._last_observation:
            self._repeated_observations += 1
        else:
            self._last_observation = observation
            self._last_warned_observation = None
            self._repeated_observations = 1
        if self.state is not None:
            self.state.repeated_observations = self._repeated_observations

    def _handle_no_progress(self) -> None:
        if self._repeated_observations >= self.no_progress_stop_threshold:
            raise AgentNoProgressError(
                "Agent stopped because the same tool call and observation "
                f"repeated {self._repeated_observations} times."
            )
        if (
            self._repeated_observations >= self.no_progress_warning_threshold
            and self._last_warned_observation != self._last_observation
        ):
            self._last_warned_observation = self._last_observation
            if self.state is not None:
                self.state.no_progress_warnings += 1
                self.state.messages.append(
                    {"role": "user", "content": NO_PROGRESS_WARNING}
                )

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
