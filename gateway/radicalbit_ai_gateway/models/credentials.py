from datetime import datetime
from typing import Generic

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic.alias_generators import to_camel

# typing_extensions: a TypeVar default needs Python 3.13.
from typing_extensions import TypeVar

# A secret as the configuration holds it (str), or as a response shows it
# (SecretStr, masked).
SecretValue = TypeVar('SecretValue', str, SecretStr, default=str)


class Credentials(BaseModel, Generic[SecretValue]):
    model_config = ConfigDict(extra='forbid')

    api_key: SecretValue | None = Field(
        default=None,
        description='API key for authentication',
        examples=['sk-your_api_key'],
    )
    api_base: str | None = Field(
        default=None,
        description='Base URL for the API, e.g., https://api.example.com',
        examples=['https://api.example.com'],
    )
    api_version: str | datetime | None = Field(
        default=None,
        description='API version to use, e.g., 2023-10-01',
        examples=['2023-10-01'],
    )
    azure_ad_token: str | None = Field(
        default=None,
        description='Azure AD token for authentication',
        examples=['your_azure_ad_token'],
    )
    project_id: str | None = Field(
        default=None,
        description='Project ID for the model, used in some APIs',
        examples=['your_project_id'],
    )
    region: str | None = Field(
        default=None,
        description='Region for the model, used in some APIs',
        examples=['us-west', 'eu-central'],
    )
    organization: str | None = Field(
        default=None,
        description='Organization for the model, used in some APIs',
        examples=['org-123'],
    )
    base_url: str | None = Field(
        default=None,
        description='Base URL for self-hosted models like Ollama',
        examples=['http://localhost:11434/v1'],
    )


class CredentialsOut(Credentials[SecretStr]):
    api_key: SecretStr | None

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


# The credentials a model holds: the configuration's, or a response's.
CredentialsT = TypeVar('CredentialsT', Credentials, CredentialsOut, default=Credentials)
