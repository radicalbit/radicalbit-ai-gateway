import asyncio
from decimal import Decimal
import json
import logging
import time
from typing import Any, Literal

try:
    from typing import Self
except ImportError:
    from typing_extensions import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from radicalbit_ai_gateway.llm.chat_model import ChatModel
from radicalbit_ai_gateway.llm.embeddings import Embeddings
from radicalbit_ai_gateway.llm.messages import AIMessage, AIMessageChunk, BaseMessage
from radicalbit_ai_gateway.models.credentials import Credentials
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.utils.app_config import get_app_config

app_config = get_app_config()
logging_config_dict = app_config.log_config.model_dump()
logger = logging.getLogger(app_config.log_config.logger_name)

# Gateway-specific param keys intercepted before forwarding params to the provider
ENABLE_PROMPT_CACHE_PARAM = 'enable_prompt_cache'


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')

    model_id: str = Field(
        ...,
        description='Unique name for the model configuration.',
        examples=['example_model', 'another_model', 'azure'],
    )
    model: str = Field(
        ...,
        description='Model identifier, provider/type',
        examples=['openai/gpt-3.5-turbo'],
    )
    credentials: Credentials | None = Field(
        default=None,
        description='Credentials for accessing the model API.',
    )
    params: dict | None = Field(
        default=None,
        description='Parameters for the model, such as temperature and max tokens.',
    )
    retry_attempts: int | None = Field(
        default=3,
        description='Number of retry attempts for API calls.',
        ge=0,
        examples=[1, 3, 5],
    )
    prompt: str | None = Field(
        default=None,
        description='Prompt to set the context for the model.',
        examples=[
            'You are a helpful assistant.',
            'You are a chatbot that answers questions.',
        ],
    )
    prompt_ref: str | None = Field(
        default=None,
        description=(
            'Reference (path/filename) to a Markdown file containing the system prompt. '
            'The file content is loaded at startup. Mutually exclusive with `prompt`.'
        ),
        examples=['customer_service.md', 'prompts/system_prompt.md'],
    )
    role: Literal['developer', 'user', 'system', 'assistant'] = Field(
        default='system',
        description='The role of the entity that is providing the message.',
    )
    input_cost_per_million_tokens: Decimal = Field(
        default=Decimal(),
        description='Cost for a million input tokens.',
    )
    output_cost_per_million_tokens: Decimal = Field(
        default=Decimal(),
        description='Cost for a million output tokens.',
    )
    input_cached_cost_per_million_tokens: Decimal = Field(
        default=Decimal(),
        description='Cost for a million cached input tokens (cache read).',
    )
    input_cache_creation_5m_cost_per_million_tokens: Decimal = Field(
        default=Decimal(),
        description='Cost for a million cache-creation input tokens — 5-minute TTL (Anthropic-specific).',
    )
    input_cache_creation_1h_cost_per_million_tokens: Decimal = Field(
        default=Decimal(),
        description='Cost for a million cache-creation input tokens — 1-hour TTL (Anthropic-specific).',
    )
    input_cost_per_second: Decimal = Field(
        default=Decimal(),
        description='Cost per second of audio input (duration-based billing, e.g. whisper-1).',
    )
    input_cost_per_audio_token: Decimal = Field(
        default=Decimal(),
        description='Cost for an audio input token, distinct from a text input token (e.g. gpt-4o-transcribe family).',
    )

    @field_validator(
        'input_cost_per_million_tokens', 'output_cost_per_million_tokens', mode='before'
    )
    @classmethod
    def convert_float_to_decimal(cls, v):
        """Convert float to Decimal if needed for precise cost calculations."""
        if v is None:
            return Decimal()
        if isinstance(v, float):
            return Decimal(str(v))
        if isinstance(v, int | str):
            return Decimal(v)
        return v

    @computed_field
    @property
    def input_cost_per_token(self) -> Decimal:
        return self.input_cost_per_million_tokens / Decimal('1000000')

    @computed_field
    @property
    def output_cost_per_token(self) -> Decimal:
        return self.output_cost_per_million_tokens / Decimal('1000000')

    @computed_field
    @property
    def input_cached_cost_per_token(self) -> Decimal:
        return self.input_cached_cost_per_million_tokens / Decimal('1000000')

    @computed_field
    @property
    def input_cache_creation_5m_cost_per_token(self) -> Decimal:
        return self.input_cache_creation_5m_cost_per_million_tokens / Decimal('1000000')

    @computed_field
    @property
    def input_cache_creation_1h_cost_per_token(self) -> Decimal:
        return self.input_cache_creation_1h_cost_per_million_tokens / Decimal('1000000')

    @computed_field
    @property
    def effective_prompt(self) -> str | None:
        if self.prompt_ref:
            pm = PromptManager.get_global() or PromptManager(
                conf=app_config.prompt_manager_config
            )
            return pm.get_model_prompt(self.prompt_ref)
        return self.prompt

    @model_validator(mode='before')
    @classmethod
    def validate_prompt_and_role(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        prompt = data.get('prompt')
        prompt_ref = data.get('prompt_ref')
        role = data.get('role', 'system')

        has_prompt = bool(prompt and prompt.strip())
        has_prompt_ref = bool(prompt_ref and str(prompt_ref).strip())

        if has_prompt and has_prompt_ref:
            raise ValueError("Only one between 'prompt' and 'prompt_ref' can be set.")

        if (has_prompt or has_prompt_ref) and role not in ('system', 'developer'):
            raise ValueError(
                "When using 'prompt' or 'prompt_ref', 'role' must be either 'system' or 'developer'."
            )

        return data

    @model_validator(mode='after')
    def set_costs(self) -> Self:
        try:
            with open('radicalbit_ai_gateway/resources/model_prices.json') as f:
                costs = json.load(f)
        except FileNotFoundError:
            logger.error('Model prices file not found. Skipping cost assignment.')
            return self
        except json.JSONDecodeError:
            logger.error(
                'Error decoding JSON from model prices file. Skipping cost assignment.'
            )
            return self
        model = self.model
        if self.model not in costs and '/' in self.model:
            if self.model.startswith('mistralai/'):
                # `mistralai/` prefix is not in the model prices file, replace with `mistral/`
                model = 'mistral/' + self.model.split('/', 1)[1]
            else:
                # `openai/gpt-5.1` in the config but on the model prices is `gpt-5.1`
                model = self.model.split('/', 1)[1]
        if not self.input_cost_per_million_tokens:
            cost_per_token = costs.get(model, {}).get('input_cost_per_token')
            if cost_per_token:
                self.input_cost_per_million_tokens = Decimal(
                    str(cost_per_token)
                ) * Decimal('1000000')
        if not self.output_cost_per_million_tokens:
            cost_per_token = costs.get(model, {}).get('output_cost_per_token')
            if cost_per_token:
                self.output_cost_per_million_tokens = Decimal(
                    str(cost_per_token)
                ) * Decimal('1000000')
        if not self.input_cached_cost_per_million_tokens:
            cost_per_token = costs.get(model, {}).get('cache_read_input_token_cost')
            if cost_per_token:
                self.input_cached_cost_per_million_tokens = Decimal(
                    str(cost_per_token)
                ) * Decimal('1000000')
        if not self.input_cache_creation_5m_cost_per_million_tokens:
            cost_per_token = costs.get(model, {}).get('cache_creation_input_token_cost')
            if cost_per_token:
                self.input_cache_creation_5m_cost_per_million_tokens = Decimal(
                    str(cost_per_token)
                ) * Decimal('1000000')
        if not self.input_cache_creation_1h_cost_per_million_tokens:
            cost_per_token = costs.get(model, {}).get(
                'cache_creation_input_token_cost_above_1hr'
            )
            if cost_per_token:
                self.input_cache_creation_1h_cost_per_million_tokens = Decimal(
                    str(cost_per_token)
                ) * Decimal('1000000')
        if not self.input_cost_per_second:
            cost_per_second = costs.get(model, {}).get('input_cost_per_second')
            if cost_per_second:
                self.input_cost_per_second = Decimal(str(cost_per_second))
        if not self.input_cost_per_audio_token:
            cost_per_audio_token = costs.get(model, {}).get(
                'input_cost_per_audio_token'
            )
            if cost_per_audio_token:
                self.input_cost_per_audio_token = Decimal(str(cost_per_audio_token))
        return self

    @model_validator(mode='after')
    def check_api_key_openai(self) -> Self:
        if not self.model.startswith('openai'):
            return self
        if self.credentials is None:
            return self
        if self.credentials.base_url and not self.credentials.api_key:
            self.credentials.api_key = 'dummy-api-key'
        return self

    @model_validator(mode='after')
    def resolve_prompt_ref(self) -> Self:
        if not self.prompt_ref:
            return self

        prompt_manager = PromptManager.get_global() or PromptManager(
            conf=app_config.prompt_manager_config
        )
        try:
            prompt_manager.get_model_prompt(self.prompt_ref)
        except FileNotFoundError as e:
            raise ValueError(f'Prompt file not found: {self.prompt_ref}') from e
        return self


# Mock models for testing purposes
class MockGatewayChatModel(ChatModel):
    """Mock chat model for testing and benchmarking purposes.

    Answers with a fixed text after a configurable latency; streaming yields
    the text word by word.
    """

    _gen_ai_provider = 'mock'

    def __init__(self, model_name: str, latency_ms: int, response_text: str):
        self.model_name = model_name
        self.model = model_name
        self._latency_ms = latency_ms
        self._response_text = response_text

    async def _agenerate(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        """Generate a mock response with configurable latency."""
        await asyncio.sleep(self._latency_ms / 1000.0)
        return AIMessage(
            content=self._response_text,
            response_metadata={
                'model': self.model_name,
                'model_name': self.model_name,
                'latency_ms': self._latency_ms,
            },
            usage_metadata={
                'input_tokens': 0,
                'output_tokens': 0,
                'total_tokens': 0,
            },
        )

    async def _astream(self, messages: list[BaseMessage], **kwargs: Any):
        """Mock behavior for streaming by yielding words."""
        await asyncio.sleep(self._latency_ms / 1000.0)
        words = self._response_text.split()
        for i, word in enumerate(words):
            # simulate small delay between words
            await asyncio.sleep(0.01)
            yield AIMessageChunk(
                content=word + (' ' if i < len(words) - 1 else ''),
                usage_metadata={
                    'input_tokens': 0,
                    'output_tokens': len(words) if i == len(words) - 1 else 0,
                    'total_tokens': len(words) if i == len(words) - 1 else 0,
                }
                if i == len(words) - 1
                else None,
            )


class MockGatewayEmbeddings(Embeddings):
    """Mock embeddings model for testing and benchmarking purposes."""

    def __init__(self, latency_ms: int, vector_size: int):
        self._latency_ms = latency_ms
        self._vector_size = vector_size

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Generate mock embeddings for a list of documents with configurable latency."""
        time.sleep(self._latency_ms / 1000.0)
        return [
            [float((hash(t) + i) % 100) / 100.0 for i in range(self._vector_size)]
            for t in texts
        ]

    def embed_query(self, text: str) -> list[float]:
        """Generate mock embedding for a single query with configurable latency."""
        time.sleep(self._latency_ms / 1000.0)
        return [float((hash(text) + i) % 100) / 100.0 for i in range(self._vector_size)]
