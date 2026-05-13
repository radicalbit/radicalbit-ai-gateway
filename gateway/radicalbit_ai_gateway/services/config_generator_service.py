from importlib import resources
import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import (
    ProjectConfigValidationError,
    ProjectInternalError,
)
from radicalbit_ai_gateway.utils.yaml_utils import validate_gateway_config

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


class YamlOut(BaseModel):
    yaml_content: str


def _load_system_prompt() -> str:
    pkg = resources.files('radicalbit_ai_gateway.services.prompts')
    return (pkg / 'config_generator_system_prompt.md').read_text(encoding='utf-8')


class ConfigGeneratorService:
    async def generate_config(self, description: str, current_draft: str | None) -> str:
        config = app_config.config_generator_config
        if not config.config_generator_openai_api_key:
            raise ProjectInternalError(
                'Config generator is not configured (missing API key)'
            )

        llm_kwargs: dict = {
            'api_key': config.config_generator_openai_api_key.get_secret_value(),
            'model': config.config_generator_openai_model,
        }
        if config.config_generator_openai_base_url:
            llm_kwargs['base_url'] = config.config_generator_openai_base_url
        llm = ChatOpenAI(**llm_kwargs)
        structured_llm = llm.with_structured_output(YamlOut)

        system_prompt = _load_system_prompt()

        user_content = f'User description: {description}'
        if current_draft:
            user_content += (
                f'\n\nCurrent draft config (use as starting point):\n{current_draft}'
            )

        messages: list = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content),
        ]

        last_error: str | None = None
        for attempt in range(config.config_generator_max_retries):
            if last_error:
                messages.append(
                    HumanMessage(
                        content=(
                            'Your previous attempt produced an invalid configuration. '
                            f'Fix this error and try again:\n{last_error}'
                        )
                    )
                )

            try:
                result: YamlOut = await structured_llm.ainvoke(messages)
            except Exception as e:
                raise ProjectInternalError(f'Config generation failed: {e}') from e

            try:
                return validate_gateway_config(result.yaml_content, check_secrets=False)
            except ProjectConfigValidationError as e:
                last_error = str(e)
                logger.warning(
                    'Generated config failed validation (attempt %d/%d): %s',
                    attempt + 1,
                    config.config_generator_max_retries,
                    last_error,
                )

        raise ProjectConfigValidationError(
            f'Failed to generate a valid config after '
            f'{config.config_generator_max_retries} attempts. '
            f'Last error: {last_error}'
        )
