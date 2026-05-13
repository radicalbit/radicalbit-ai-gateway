import logging

from pydantic import BaseModel

from radicalbit_ai_gateway.utils.app_config import get_app_config

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


class JudgeResult(BaseModel):
    """Structured result returned by the LLM judge."""

    triggered: bool
    reasoning: str | None = None
    violation_type: str | None = None
