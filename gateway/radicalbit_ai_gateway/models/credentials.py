from datetime import datetime

from pydantic import BaseModel, Field


class Credentials(BaseModel):
    api_key: str | None = Field(
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
