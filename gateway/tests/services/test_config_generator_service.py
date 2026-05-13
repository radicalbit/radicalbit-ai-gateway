import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import SecretStr
import pytest

from radicalbit_ai_gateway.services.config_generator_service import (
    ConfigGeneratorService,
    YamlOut,
)
from radicalbit_ai_gateway.utils.app_config import ConfigGeneratorConfig
from radicalbit_ai_gateway.utils.exceptions import (
    ProjectConfigValidationError,
    ProjectInternalError,
)

_VALID_YAML = (
    'chat_models:\n'
    '- model_id: gpt4o\n'
    '  model: openai/gpt-4o\n'
    '  credentials:\n'
    '    api_key: YOUR_OPENAI_API_KEY\n'
    'routes:\n'
    '  my-route:\n'
    '    chat_models:\n'
    '    - gpt4o\n'
)

_INVALID_YAML = (
    'chat_models:\n'
    '- model_id: gpt4o\n'
    '  model: openai/gpt-4o\n'
    'routes:\n'
    '  my-route:\n'
    '    chat_models:\n'
    '    - nonexistent-model\n'
)


def _mock_llm(*yaml_contents: str):
    side_effect = [YamlOut(yaml_content=c) for c in yaml_contents]
    mock_runnable = MagicMock()
    mock_runnable.ainvoke = AsyncMock(side_effect=side_effect)
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_runnable
    return mock_llm


class TestConfigGeneratorService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.svc = ConfigGeneratorService()

    async def test_generate_returns_valid_yaml(self):
        with (
            patch(
                'radicalbit_ai_gateway.services.config_generator_service.app_config.config_generator_config',
                ConfigGeneratorConfig(
                    config_generator_openai_api_key=SecretStr('sk-test')
                ),
            ),
            patch(
                'radicalbit_ai_gateway.services.config_generator_service.ChatOpenAI',
                return_value=_mock_llm(_VALID_YAML),
            ),
        ):
            result = await self.svc.generate_config('Simple OpenAI route', None)
        assert 'gpt4o' in result
        assert 'routes' in result

    async def test_credential_placeholder_present_in_output(self):
        with (
            patch(
                'radicalbit_ai_gateway.services.config_generator_service.app_config.config_generator_config',
                ConfigGeneratorConfig(
                    config_generator_openai_api_key=SecretStr('sk-test')
                ),
            ),
            patch(
                'radicalbit_ai_gateway.services.config_generator_service.ChatOpenAI',
                return_value=_mock_llm(_VALID_YAML),
            ),
        ):
            result = await self.svc.generate_config('Simple OpenAI route', None)
        assert 'YOUR_OPENAI_API_KEY' in result

    async def test_retries_on_validation_failure(self):
        with (
            patch(
                'radicalbit_ai_gateway.services.config_generator_service.app_config.config_generator_config',
                ConfigGeneratorConfig(
                    config_generator_openai_api_key=SecretStr('sk-test')
                ),
            ),
            patch(
                'radicalbit_ai_gateway.services.config_generator_service.ChatOpenAI',
                return_value=_mock_llm(_INVALID_YAML, _VALID_YAML),
            ) as m,
        ):
            result = await self.svc.generate_config('desc', None)
        m.return_value.with_structured_output.return_value.ainvoke.assert_called()
        assert 'routes' in result

    async def test_raises_after_all_retries_fail(self):
        with (
            patch(
                'radicalbit_ai_gateway.services.config_generator_service.app_config.config_generator_config',
                ConfigGeneratorConfig(
                    config_generator_openai_api_key=SecretStr('sk-test'),
                    config_generator_max_retries=2,
                ),
            ),
            patch(
                'radicalbit_ai_gateway.services.config_generator_service.ChatOpenAI',
                return_value=_mock_llm(_INVALID_YAML, _INVALID_YAML),
            ) as m,
            pytest.raises(ProjectConfigValidationError),
        ):
            await self.svc.generate_config('desc', None)
        assert (
            m.return_value.with_structured_output.return_value.ainvoke.call_count == 2
        )

    async def test_raises_internal_error_on_llm_exception(self):
        mock_runnable = MagicMock()
        mock_runnable.ainvoke = AsyncMock(side_effect=Exception('network error'))
        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_runnable
        with (
            patch(
                'radicalbit_ai_gateway.services.config_generator_service.app_config.config_generator_config',
                ConfigGeneratorConfig(
                    config_generator_openai_api_key=SecretStr('sk-test')
                ),
            ),
            patch(
                'radicalbit_ai_gateway.services.config_generator_service.ChatOpenAI',
                return_value=mock_llm,
            ),
            pytest.raises(ProjectInternalError),
        ):
            await self.svc.generate_config('desc', None)

    async def test_raises_when_no_api_key(self):
        with (
            patch(
                'radicalbit_ai_gateway.services.config_generator_service.app_config.config_generator_config',
                ConfigGeneratorConfig(config_generator_openai_api_key=None),
            ),
            pytest.raises(ProjectInternalError),
        ):
            await self.svc.generate_config('desc', None)

    async def test_current_draft_included_in_message(self):
        with (
            patch(
                'radicalbit_ai_gateway.services.config_generator_service.app_config.config_generator_config',
                ConfigGeneratorConfig(
                    config_generator_openai_api_key=SecretStr('sk-test')
                ),
            ),
            patch(
                'radicalbit_ai_gateway.services.config_generator_service.ChatOpenAI',
                return_value=_mock_llm(_VALID_YAML),
            ) as m,
        ):
            await self.svc.generate_config('Add rate limiting', 'current: draft')
        call_args = (
            m.return_value.with_structured_output.return_value.ainvoke.call_args[0][0]
        )
        assert 'current: draft' in call_args[-1].content
