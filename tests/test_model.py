import os
import unittest
from unittest.mock import Mock, patch

from agent.model import ModelClient, ModelClientError, ModelConfig, ModelConfigError


class ModelConfigTests(unittest.TestCase):
    @patch("agent.model.load_dotenv")
    def test_loads_configuration_from_environment(self, load_dotenv: Mock) -> None:
        # 验证 OPENAI_API_KEY、OPENAI_BASE_URL 和 MODEL_NAME 能否正确转换为 ModelConfig
        values = {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_BASE_URL": "https://example.com/v1",
            "MODEL_NAME": "test-model",
        }

        with patch.dict(os.environ, values, clear=True):
            config = ModelConfig.from_env()

        self.assertEqual(config.api_key, "test-key")
        self.assertEqual(config.base_url, "https://example.com/v1")
        self.assertEqual(config.model_name, "test-model")
        load_dotenv.assert_called_once_with(override=False)

    @patch("agent.model.load_dotenv")
    def test_rejects_missing_required_configuration(self, load_dotenv: Mock) -> None:
        # 验证缺少 OPENAI_API_KEY 或 MODEL_NAME 时是否会引发 ModelConfigError
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                ModelConfigError, "OPENAI_API_KEY, MODEL_NAME"
            ):
                ModelConfig.from_env()


class ModelClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sdk_client = Mock()
        self.config = ModelConfig(api_key="test-key", model_name="test-model")
        self.client = ModelClient(config=self.config, client=self.sdk_client)

    def test_sends_chat_completion_request(self) -> None:
        # 验证是否能正确发送聊天完成请求
        messages = [{"role": "user", "content": "Hello"}]
        tools = [{"type": "function", "function": {"name": "read_file"}}]
        expected_response = Mock()
        self.sdk_client.chat.completions.create.return_value = expected_response

        response = self.client.chat(messages, tools)

        self.assertIs(response, expected_response)
        self.sdk_client.chat.completions.create.assert_called_once_with(
            model="test-model",
            messages=messages,
            tools=tools,
        )

    def test_wraps_request_errors(self) -> None:
        # 验证请求错误是否会被包装为 ModelClientError
        self.sdk_client.chat.completions.create.side_effect = RuntimeError("network")

        with self.assertRaises(ModelClientError) as context:
            self.client.chat([{"role": "user", "content": "Hello"}])

        self.assertIsInstance(context.exception.__cause__, RuntimeError)


if __name__ == "__main__":
    unittest.main()
