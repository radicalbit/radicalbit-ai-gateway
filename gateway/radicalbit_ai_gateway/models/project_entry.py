from typing import NamedTuple
from uuid import UUID

from radicalbit_ai_gateway.models.gateway_config import GatewayConfig


class ProjectEntry(NamedTuple):
    """Bundles project uuid and gateway config in the project_configs dict."""

    uuid: UUID
    config: GatewayConfig
