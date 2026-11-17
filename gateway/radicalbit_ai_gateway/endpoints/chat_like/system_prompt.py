"""The route's system prompt, added to a chat-like request's messages."""

import logging

from radicalbit_ai_gateway.endpoints.chat_like.openai_messages import (
    select_message_by_role,
)
from radicalbit_ai_gateway.llm.messages import BaseMessage, SystemMessage
from radicalbit_ai_gateway.models.model import ENABLE_PROMPT_CACHE_PARAM, Model
from radicalbit_ai_gateway.utils.app_config import get_app_config

logger = logging.getLogger(get_app_config().log_config.logger_name)


def apply_config_prompt(messages: list[BaseMessage], model_selected: Model) -> int:
    """Prepend the route's configured system prompt to *messages* in place.

    Runs *after* preprocessing so the configured prompt is never exposed to
    preprocessing plugins. Return how many messages it added (0 or 1).
    """
    config_prompt, role = model_selected.effective_prompt, model_selected.role

    logger.debug(
        'Config prompt for model %s: %s and role: %s',
        model_selected.model_id,
        config_prompt,
        role,
    )

    if config_prompt:
        logger.debug('Adding config prompt to messages')
        enable_prompt_cache = bool(
            (model_selected.params or {}).get(ENABLE_PROMPT_CACHE_PARAM, False)
        )
        if model_selected.model.startswith('anthropic/') and enable_prompt_cache:
            # Wrap the system prompt as a content block with cache_control so Anthropic
            # caches it across requests (requires enable_prompt_cache: true in model params)
            system_msg = SystemMessage(
                content=[
                    {
                        'type': 'text',
                        'text': config_prompt,
                        'cache_control': {'type': 'ephemeral'},
                    }
                ]
            )
        else:
            system_msg = select_message_by_role(
                content=config_prompt, role=role, tool_calls=[], tool_call_id=None
            )
        messages[:] = [system_msg, *messages]
        return 1
    return 0
