from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class RequestIdentity:
    """Who made a request, and where: what every event it causes carries.

    Limiters count usage after the call, deep inside the gateway, where the
    request itself is out of reach. They are handed this instead.
    """

    request_uuid: str
    route_name: str
    api_key_uuid: str
    api_key_name: str
    group_uuid: str
    group_name: str
    project_uuid: str = ''
    project_name: str = ''

    def event_fields(self) -> dict[str, Any]:
        """Return the fields an ``EventBase`` payload takes from the request."""
        return asdict(self)
