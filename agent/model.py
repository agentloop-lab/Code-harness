"""OpenAI-compatible model client."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from dotenv import load_dotenv


class ModelConfigError(ValueError):
    """Raised when required model configuration is missing."""


class ModelClientError(RuntimeError):
    """Raised when a model request fails."""


@dataclass(frozen=True)
class ModelConfig:
    """Configuration loaded from environment variables."""

    api_key: str
    model_name: str
    base_url: str | None = None

    @classmethod
    def from_env(cls) -> "ModelConfig":
        load_dotenv(override=False)

        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        model_name = os.getenv("MODEL_NAME", "").strip()
        base_url = os.getenv("OPENAI_BASE_URL", "").strip() or None

        missing = []
        if not api_key:
            missing.append("OPENAI_API_KEY")
        if not model_name:
            missing.append("MODEL_NAME")
        if missing:
            names = ", ".join(missing)
            raise ModelConfigError(f"Missing required environment variables: {names}")

        return cls(api_key=api_key, model_name=model_name, base_url=base_url)


class ModelClient:
    """Send chat completion requests through an OpenAI-compatible API."""

    def __init__(self, config: ModelConfig | None = None, client: Any = None) -> None:
        self.config = config or ModelConfig.from_env()
        self._client = client or self._create_client()

    def _create_client(self) -> Any:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ModelClientError(
                "The openai package is required. Install dependencies with "
                "'python -m pip install -r requirements.txt'."
            ) from exc

        options: dict[str, str] = {"api_key": self.config.api_key}
        if self.config.base_url:
            options["base_url"] = self.config.base_url
        return OpenAI(**options)

    def chat(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]] | None = None,
    ) -> Any:
        request: dict[str, Any] = {
            "model": self.config.model_name,
            "messages": list(messages),
        }
        if tools:
            request["tools"] = list(tools)

        try:
            return self._client.chat.completions.create(**request)
        except Exception as exc:
            raise ModelClientError("Model request failed.") from exc
