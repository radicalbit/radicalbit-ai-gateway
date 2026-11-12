from pydantic import BaseModel, ConfigDict, Field


class DecisionRequest(BaseModel):
    """Typesafe's own `POST /v1/systemone` body (ADR 0004).

    The gateway reads only `model`. Every other field, `state` and `questions`
    included, is kept as sent and validated by Typesafe.
    """

    model_config = ConfigDict(extra='allow')

    model: str = Field(
        ...,
        description='Route key, `project/route`.',
        examples=['my-project/agent'],
    )
