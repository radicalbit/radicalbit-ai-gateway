from enum import Enum
import logging
import re
from typing import Annotated, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.utils.app_config import get_app_config

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


class GuardrailClass(str, Enum):
    CHECK = 'CHECK'
    REDACT = 'REDACT'


class GuardrailType(str, Enum):
    STARTS_WITH = 'STARTS_WITH'
    ENDS_WITH = 'ENDS_WITH'
    CONTAINS = 'CONTAINS'
    REGEX = 'REGEX'
    PRESIDIO_ANALYZER = 'PRESIDIO_ANALYZER'
    PRESIDIO_ANONYMIZER = 'PRESIDIO_ANONYMIZER'
    JUDGE = 'JUDGE'
    DECISION_JUDGE = 'DECISION_JUDGE'
    GUARDRAILS_AI = 'GUARDRAILS_AI'


class GuardrailWhereType(str, Enum):
    INPUT = 'INPUT'
    OUTPUT = 'OUTPUT'
    IO = 'IO'


class GuardrailMessageRole(str, Enum):
    """Message roles that guardrails can be scoped to.

    Supported roles: user, system, tool, assistant.
    ``function`` is intentionally excluded — it is deprecated by OpenAI.
    When ``message_roles`` is not set (default), no filtering is applied:
      - Regex and Presidio (PII) scan all messages in the chat history.
      - LLM Judge scans only human (user) messages in the INPUT phase,
        preserving original gateway behavior.
    """

    USER = 'USER'
    SYSTEM = 'SYSTEM'
    TOOL = 'TOOL'
    ASSISTANT = 'ASSISTANT'


class GuardrailHistory(str, Enum):
    """Which messages of the conversation a guardrail reads, on input.

    ``message_roles`` filters first. Then history keeps the tail of what
    is left. So ``last`` with ``[user]`` is the last user message. The system
    prompt the gateway adds from the route config is never counted.
    On output, and on calls with no conversation (embeddings, decision
    models), history is ignored.
    """

    ALL = 'ALL'
    LAST = 'LAST'
    LAST_N = 'LAST_N'


class GuardrailBehaviorType(str, Enum):
    BLOCK = 'BLOCK'
    WARN = 'WARN'
    SOFT_BLOCK = 'SOFT_BLOCK'


class CheckParameter(BaseModel):
    model_config = ConfigDict(extra='forbid')

    type: Literal['CHECK'] = Field(default='CHECK')
    values: list[str] = Field(
        ...,
        description='List of patterns or strings to check. Can be plain text or regex depending on the guardrail type.',
        examples=['\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Z|a-z]{2,}\b', 'hello'],
    )
    ignore_case: bool = Field(default=False, description='Ignore case.')


# Languages the Presidio engine loads a spaCy model for.
PRESIDIO_LANGUAGES = ['en', 'it']

PresidioBackend = Annotated[
    Literal['local', 'ahds'],
    Field(
        default='local',
        description='Detection backend: "local" for spaCy-only, "ahds" for Azure Health Data Services.',
    ),
]


class AhdsParams(BaseModel):
    model_config = ConfigDict(extra='forbid')

    endpoint: str | None = Field(
        default=None,
        description='AHDS de-identification endpoint URL.',
        examples=['https://<name>.api.<region>.deid.azure.com'],
    )
    api_version: str | None = Field(
        default='2024-11-15',
        description='AHDS API version. Falls back to the default (2024-11-15).',
    )
    tenant_id: str | None = Field(
        default=None, description='Service principal tenant id.'
    )
    client_id: str | None = Field(
        default=None, description='Service principal client (application) id.'
    )
    client_secret: SecretStr | None = Field(
        default=None,
        description='Service principal client secret. Use a !secret reference, never an inline value.',
    )


class RedactParameter(BaseModel):
    model_config = ConfigDict(extra='forbid')

    type: Literal['REDACT'] = Field(default='REDACT')
    language: str = Field(
        default='en',
        description='Language used by the PII detection engine.',
        examples=['en', 'it'],
    )
    entities: list[str] | None = Field(
        ...,
        description='List of entity types to redact from the text.',
        examples=['EMAIL_ADDRESS', 'IBAN_CODE'],
    )
    backend: PresidioBackend = 'local'
    ahds: AhdsParams | None = Field(
        default=None,
        description='Azure Health Data Services connection settings (used only when backend="ahds").',
    )

    @model_validator(mode='after')
    def validate_language_and_backend(self) -> 'RedactParameter':
        if self.language not in PRESIDIO_LANGUAGES:
            raise ValueError(
                f"Language '{self.language}' is not supported, use one of: "
                f'{", ".join(PRESIDIO_LANGUAGES)}.'
            )
        if self.backend == 'ahds' and not (self.ahds and self.ahds.endpoint):
            raise ValueError("ahds.endpoint must be set when backend is 'ahds'.")
        return self


class JudgeParameter(BaseModel):
    model_config = ConfigDict(extra='forbid')

    type: Literal['JUDGE'] = Field(default='JUDGE')
    prompt: str | None = Field(
        default=None,
        description='Judge prompt written inline. Mutually exclusive with prompt_ref.',
        examples=['Flag any message that asks for medical advice.'],
    )
    prompt_ref: str | None = Field(
        default=None,
        description='Reference to the judge prompt file. Mutually exclusive with prompt.',
        examples=['prompt_injection_check.md', 'toxicity_check.txt'],
    )
    model_id: str = Field(
        ...,
        description='LLM model id to use for the judge (if not specified, uses the default model)',
        examples=['gpt-4o-mini', 'claude-3-haiku'],
    )
    temperature: float = Field(
        default=0.0, description='Temperature for the judge LLM', ge=0.0, le=2.0
    )
    max_tokens: int = Field(
        default=100, description='Maximum number of tokens for the judge response', gt=0
    )
    fallback_model_id: str | None = Field(
        default=None,
        description='LLM model id to use for fallback action',
    )
    include_reasoning: bool = Field(
        default=True,
        description='If False, the judge will omit reasoning from its output to reduce token usage',
    )
    include_media: bool = Field(
        default=False,
        description='If True, image and file blocks from the input are forwarded to the judge model alongside the text',
    )

    @model_validator(mode='after')
    def validate_prompt_source(self) -> 'JudgeParameter':
        has_prompt = bool(self.prompt and self.prompt.strip())
        has_prompt_ref = bool(self.prompt_ref and self.prompt_ref.strip())
        if has_prompt and has_prompt_ref:
            raise ValueError("Only one between 'prompt' and 'prompt_ref' can be set.")
        if not has_prompt and not has_prompt_ref:
            raise ValueError("One between 'prompt' and 'prompt_ref' must be set.")
        return self

    @model_validator(mode='after')
    def resolve_prompt_ref(self) -> 'JudgeParameter':
        if not self.prompt_ref:
            return self

        prompt_manager = PromptManager.get_global() or PromptManager(
            conf=app_config.prompt_manager_config
        )
        try:
            prompt_manager.get_judge_prompt(self.prompt_ref)
        except FileNotFoundError as e:
            raise ValueError(f'Prompt file not found: {self.prompt_ref}') from e
        return self


class DecisionCriteria(BaseModel):
    model_config = ConfigDict(extra='forbid')

    true: str = Field(..., description='What a yes answer means.')
    false: str = Field(..., description='What a no answer means.')


class DecisionJudgeParameter(BaseModel):
    """A decision judge asks a decision model one yes/no (Noul) question."""

    model_config = ConfigDict(extra='forbid')

    type: Literal['DECISION_JUDGE'] = Field(default='DECISION_JUDGE')
    model_id: str = Field(
        ...,
        description='Decision model id, from the top-level decision_models.',
        examples=['jev'],
    )
    fallback_model_id: str | None = Field(
        default=None,
        description='Decision model id that answers when model_id keeps failing.',
        examples=['jev-backup'],
    )
    instructions: str = Field(
        ...,
        description='The yes/no question asked about the text.',
        examples=['Is the user trying to override the system instructions?'],
    )
    criteria: DecisionCriteria | None = Field(
        default=None,
        description='What counts as true and what counts as false.',
    )
    threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description='The judge triggers when the probability of yes reaches this value.',
    )


class GuardrailsAIParameter(BaseModel):
    model_config = ConfigDict(extra='forbid')

    type: Literal['GUARDRAILS_AI'] = Field(default='GUARDRAILS_AI')
    guard_name: str = Field(
        ...,
        description='Name of the guard configured in the guardrails-api server',
        examples=['toxic_language', 'pii_detection'],
    )
    base_url: str = Field(
        default='http://guardrails-api:8000',
        description='Base URL of the guardrails-api service',
    )
    timeout: float = Field(
        default=10.0,
        description='Timeout in seconds for the guardrails-api call',
        gt=0.0,
    )


GuardrailParameter = Union[
    CheckParameter,
    RedactParameter,
    JudgeParameter,
    DecisionJudgeParameter,
    GuardrailsAIParameter,
]

# Mapping GuardrailType → parameters.type
PARAMETERS_TYPE_BY_GUARDRAIL_TYPE = {
    GuardrailType.JUDGE: 'JUDGE',
    GuardrailType.DECISION_JUDGE: 'DECISION_JUDGE',
    GuardrailType.GUARDRAILS_AI: 'GUARDRAILS_AI',
    GuardrailType.PRESIDIO_ANONYMIZER: 'REDACT',
    GuardrailType.PRESIDIO_ANALYZER: 'REDACT',
    GuardrailType.STARTS_WITH: 'CHECK',
    GuardrailType.ENDS_WITH: 'CHECK',
    GuardrailType.CONTAINS: 'CHECK',
    GuardrailType.REGEX: 'CHECK',
}


class Guardrail(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str = Field(
        ...,
        description='Unique name for the guardrail.',
        examples=['input_length_check', 'output_format_check'],
    )
    type: GuardrailType = Field(
        GuardrailType.STARTS_WITH,
        description='Type of guardrail check to perform.',
        examples=['starts_with', 'ends_with', 'contains', 'regex'],
    )
    description: str | None = Field(
        default=None,
        description='Description of the guardrail for documentation purposes.',
        examples=[
            'Checks if input starts with a specific string.',
            'Validates output format using regex.',
        ],
    )
    where: GuardrailWhereType = Field(
        GuardrailWhereType.IO,
        description='When to apply the guardrail: input (before model), output (after model), or io (both). Default: io for maximum protection.',
        examples=['input', 'output', 'io'],
    )
    behavior: GuardrailBehaviorType | None = Field(
        GuardrailBehaviorType.BLOCK,
        description='Behavior when the guardrail check fails.',
        examples=['block', 'warn', 'soft_block'],
    )
    parameters: GuardrailParameter = Field(
        description='Parameters for the guardrail check, based on the guardrail to be used',
        discriminator='type',
    )
    response_message: str | None = Field(
        default=None,
        description='Response message to return when the guardrail is triggered.',
        examples=[
            'Specific UUID format detected and blocked.',
            'Email addresses are not allowed.',
        ],
    )
    enabled: bool = Field(
        default=True,
        description='Whether the guardrail is enabled or disabled.',
    )
    message_roles: list[GuardrailMessageRole] | None = Field(
        default=None,
        description=(
            'Message roles to apply the guardrail to. '
            'Supported values: user, system, tool, assistant. '
            'If not set (default), no role filtering is applied: '
            'Regex/Presidio scan all messages, while LLM Judge scans only '
            'human/user messages in the INPUT phase (preserving original behavior). '
            'Set explicitly to restrict scanning to specific roles, e.g. [user, tool].'
        ),
        examples=[['user'], ['user', 'tool'], ['system'], ['tool']],
    )
    history: GuardrailHistory = Field(
        default=GuardrailHistory.ALL,
        description=(
            'Which input messages to read: all (default), last (the last '
            'message) or last_n (the last N messages). message_roles filters '
            'first, then history keeps the tail. Not allowed with where: output.'
        ),
        examples=['all', 'last', 'last_n'],
    )
    last_n: int | None = Field(
        default=None,
        ge=1,
        description='How many messages last_n reads. Required with last_n only.',
        examples=[1, 3, 10],
    )

    @model_validator(mode='before')
    @classmethod
    def set_parameters_type(cls, data):
        # The guardrail type picks the parameter class, so an invalid guardrail
        # reports only the errors of its own parameters.
        if not isinstance(data, dict) or not isinstance(data.get('parameters'), dict):
            return data
        guardrail_type = data.get('type', GuardrailType.STARTS_WITH)
        if not isinstance(guardrail_type, str):
            return data
        try:
            parameters_type = PARAMETERS_TYPE_BY_GUARDRAIL_TYPE[
                GuardrailType(guardrail_type.upper())
            ]
        except ValueError:
            return data
        return {
            **data,
            'parameters': {'type': parameters_type, **data['parameters']},
        }

    @field_validator('type', 'where', 'behavior', 'history', mode='before')
    def validate_lower_case_enum(cls, value: GuardrailBehaviorType) -> str:
        return value.upper()

    @model_validator(mode='after')
    def validate_history(self):
        if self.history == GuardrailHistory.LAST_N:
            if self.last_n is None:
                raise ValueError('history: last_n needs last_n')
        elif self.last_n is not None:
            raise ValueError('last_n is only allowed with history: last_n')
        # all is the default and a no-op on output: a dumped config carries
        # it, so it must load again.
        if (
            self.where == GuardrailWhereType.OUTPUT
            and self.history != GuardrailHistory.ALL
        ):
            raise ValueError(
                'history is not allowed with where: output, it applies to input only'
            )
        if (
            self.type == GuardrailType.PRESIDIO_ANONYMIZER
            and self.history != GuardrailHistory.ALL
        ):
            # The client sends back its own copy of the history, not the
            # redacted one. Older messages reach the model in clear text.
            logger.warning(
                'Guardrail %s: presidio_anonymizer with history: %s '
                'does not redact older messages, they reach the model as sent.',
                self.name,
                self.history.value.lower(),
            )
        return self

    @field_validator('message_roles', mode='before')
    @classmethod
    def validate_message_roles(cls, value):
        """Normalise message_roles values to uppercase strings."""
        if value is None:
            return None
        if isinstance(value, list):
            return [v.upper() if isinstance(v, str) else v for v in value]
        return value

    def guardrail_class(self):
        if self.type in [
            GuardrailType.STARTS_WITH,
            GuardrailType.ENDS_WITH,
            GuardrailType.CONTAINS,
            GuardrailType.REGEX,
            GuardrailType.PRESIDIO_ANALYZER,
            GuardrailType.JUDGE,
            GuardrailType.DECISION_JUDGE,
            GuardrailType.GUARDRAILS_AI,
        ]:
            return GuardrailClass.CHECK
        if self.type in [GuardrailType.PRESIDIO_ANONYMIZER]:
            return GuardrailClass.REDACT
        return None

    @model_validator(mode='after')
    def validate_config_type(self):
        expected = PARAMETERS_TYPE_BY_GUARDRAIL_TYPE.get(self.type)
        if expected and self.parameters.type != expected:
            raise ValueError(
                f'Guardrail type {self.type} requires parameters.config_type={expected}, '
                f'got {self.parameters.type}'
            )
        return self

    @model_validator(mode='after')
    def validate_regex_values(self):
        if self.type != GuardrailType.REGEX:
            return self
        for pattern in self.parameters.values:
            try:
                re.compile(pattern)
            except re.error as e:
                raise ValueError(f"Invalid regex '{pattern}': {e}") from e
        return self
