from enum import Enum

from pydantic import BaseModel, Field, field_validator


class FallbackModelType(str, Enum):
    CHAT = 'CHAT'
    EMBEDDING = 'EMBEDDING'
    TRANSCRIPTION = 'TRANSCRIPTION'


class Fallback(BaseModel):
    target: str = Field(
        ..., description='Target model id for fallback.', examples=['example_model']
    )
    fallbacks: list[str] = Field(
        description='List of fallback model id to use if the target model fails.',
        examples=[['another_model', 'azure']],
    )
    type: FallbackModelType = Field(
        default=FallbackModelType.CHAT,
        description='Type of the fallback models.',
        examples=[
            'CHAT',
            'EMBEDDING',
            'TRANSCRIPTION',
        ],
    )

    @field_validator('type', mode='before')
    def validate_lower_case_enum(cls, value: FallbackModelType) -> str:
        return value.upper()
