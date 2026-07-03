from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator


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
    GUARDRAILS_AI = 'GUARDRAILS_AI'


class GuardrailWhereType(str, Enum):
    INPUT = 'INPUT'
    OUTPUT = 'OUTPUT'
    IO = 'IO'


class GuardrailMessageRole(str, Enum):
    """Message roles that guardrails can be scoped to.

    Supported roles: user, system, tool, assistant.
    ``function`` is intentionally excluded — it is deprecated by OpenAI.
    When ``message_roles`` is not set on a guardrail, all messages in the
    list are scanned (original gateway behavior, no role filtering).
    """

    USER = 'USER'
    SYSTEM = 'SYSTEM'
    TOOL = 'TOOL'
    ASSISTANT = 'ASSISTANT'


class GuardrailBehaviorType(str, Enum):
    BLOCK = 'BLOCK'
    WARN = 'WARN'
    SOFT_BLOCK = 'SOFT_BLOCK'


class CheckParameter(BaseModel):
    type: Literal['CHECK'] = Field(default='CHECK')
    values: list[str] = Field(
        ...,
        description='List of patterns or strings to check. Can be plain text or regex depending on the guardrail type.',
        examples=['\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Z|a-z]{2,}\b', 'hello'],
    )
    ignore_case: bool = Field(default=False, description='Ignore case.')


PresidioBackend = Annotated[
    Literal['local', 'ahds'],
    Field(
        default='local',
        description='Detection backend: "local" for spaCy-only, "ahds" for Azure Health Data Services.',
    ),
]


class AhdsParams(BaseModel):
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


class JudgeParameter(BaseModel):
    type: Literal['JUDGE'] = Field(default='JUDGE')
    prompt_ref: str = Field(
        ...,
        description='Reference to the judge prompt (file path or template)',
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


class GuardrailsAIParameter(BaseModel):
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
    GuardrailsAIParameter,
]


class Guardrail(BaseModel):
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
        description='Parameters for the guardrail check, based on the guardrail to be used'
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
            'If not set (default), all messages are scanned regardless of role — '
            'preserving the original gateway behavior. '
            'Set explicitly to restrict scanning to specific roles, e.g. [user, tool].'
        ),
        examples=[['user'], ['user', 'tool'], ['system'], ['tool']],
    )

    @field_validator('type', 'where', 'behavior', mode='before')
    def validate_lower_case_enum(cls, value: GuardrailBehaviorType) -> str:
        return value.upper()

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
            GuardrailType.GUARDRAILS_AI,
        ]:
            return GuardrailClass.CHECK
        if self.type in [GuardrailType.PRESIDIO_ANONYMIZER]:
            return GuardrailClass.REDACT
        return None

    @model_validator(mode='after')
    def validate_config_type(self):
        # Mapping GuardrailType → GuardrailConfig.config_type
        mapping = {
            GuardrailType.JUDGE: 'JUDGE',
            GuardrailType.GUARDRAILS_AI: 'GUARDRAILS_AI',
            GuardrailType.PRESIDIO_ANONYMIZER: 'REDACT',
            GuardrailType.PRESIDIO_ANALYZER: 'REDACT',
            GuardrailType.STARTS_WITH: 'CHECK',
            GuardrailType.ENDS_WITH: 'CHECK',
            GuardrailType.CONTAINS: 'CHECK',
            GuardrailType.REGEX: 'CHECK',
        }
        expected = mapping.get(self.type)
        if expected and self.parameters.type != expected:
            raise ValueError(
                f'Guardrail type {self.type} requires parameters.config_type={expected}, '
                f'got {self.parameters.type}'
            )
        return self
