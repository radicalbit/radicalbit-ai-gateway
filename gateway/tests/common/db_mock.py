import datetime
import uuid
from uuid import UUID, uuid4

from radicalbit_ai_gateway.db.models.event import EventDetails
from radicalbit_ai_gateway.db.tables.event_table import Event
from radicalbit_ai_gateway.db.tables.group_route_table import GroupRoute
from radicalbit_ai_gateway.db.tables.group_table import Group
from radicalbit_ai_gateway.db.tables.key_table import Key
from radicalbit_ai_gateway.db.tables.otel_traces_table import OtelTraces
from radicalbit_ai_gateway.db.tables.project_config_table import ProjectConfig
from radicalbit_ai_gateway.db.tables.project_table import Project
from radicalbit_ai_gateway.db.tables.request_event_table import RequestEvent
from radicalbit_ai_gateway.models.api_key_dto import ApiKeySec
from radicalbit_ai_gateway.models.auth_dto import (
    GroupFullOut,
    GroupIn,
    GroupOut,
    GroupRoutesIn,
    GroupsRouteOut,
    KeyFullOut,
    KeyGroupIn,
    KeyIn,
    KeyOut,
    KeysUuidIn,
    RouteGroupsIn,
)
from radicalbit_ai_gateway.models.config_slot import Slot
from radicalbit_ai_gateway.models.config_status import ConfigStatus
from radicalbit_ai_gateway.models.project_dto import (
    ConfigSlotOut,
    ProjectConfigFileIn,
    ProjectIn,
    ProjectOut,
)
from radicalbit_ai_gateway.models.project_status import ProjectStatus
from radicalbit_ai_gateway.models.request_event_type import RequestStatus, RequestType

TEST_PROJECT_UUID = UUID('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
SAMPLE_PROJECT_UUID = UUID('aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee')
_TEST_PROJECT_UUID_KEY = 'traceloop.association.properties.project_uuid'

RANDOM_UUID = uuid.uuid4()
HASHED_KEY = 'da4af9c445b9bc1686ba63455d7c34aa569aeb09b95f395963dc7777a2afc6d4'
PLAIN_KEY = 'sk-rb-SmnyH9HPJfwyRpJ2vfZEO0ugFWykvwarbEQ2PPpTezpsueV1'
OBSCURED_KEY = 'sk-rb-Sm...eV1'
UTC = getattr(datetime, 'UTC', datetime.timezone.utc)
REQUEST_UUID = uuid.UUID(int=0)
API_KEY_UUID = uuid.UUID(int=0)
GROUP_UUID = uuid.UUID(int=0)


def get_sample_key(
    uuid: uuid.UUID = RANDOM_UUID,
    name: str = 'rb-key',
    hashed_key: str = HASHED_KEY,
    obscured_key: str = OBSCURED_KEY,
    group_uuid: uuid.UUID | None = None,
) -> Key:
    now = datetime.datetime.now(tz=UTC)
    return Key(
        uuid=uuid,
        name=name,
        owner='gateway',
        key_metadata=None,
        hashed_key=hashed_key,
        obscured_key=obscured_key,
        created_at=now,
        updated_at=now,
        group_uuid=group_uuid,
    )


def get_sample_key_with_group(
    uuid: uuid.UUID = RANDOM_UUID,
    name: str = 'rb-key',
    hashed_key: str = HASHED_KEY,
    obscured_key: str = OBSCURED_KEY,
    group_uuid: uuid.UUID = RANDOM_UUID,
) -> Key:
    now = datetime.datetime.now(tz=UTC)
    return Key(
        uuid=uuid,
        name=name,
        owner='gateway',
        key_metadata=None,
        hashed_key=hashed_key,
        obscured_key=obscured_key,
        created_at=now,
        updated_at=now,
        group_uuid=group_uuid,
        group=get_sample_group(uuid=group_uuid),
    )


def get_sample_group_plain(
    uuid: uuid.UUID = RANDOM_UUID,
    name: str = 'group',
) -> Group:
    now = datetime.datetime.now(tz=UTC)
    return Group(
        uuid=uuid,
        name=name,
        owner='gateway',
        group_metadata=None,
        created_at=now,
        updated_at=now,
    )


def get_sample_group(
    uuid: uuid.UUID = RANDOM_UUID,
    name: str = 'group',
    group_routes: list[GroupRoute] = [],
    keys: list[Key] = [],
) -> Group:
    now = datetime.datetime.now(tz=UTC)
    return Group(
        uuid=uuid,
        name=name,
        created_at=now,
        updated_at=now,
        owner='gateway',
        group_metadata=None,
        group_routes=group_routes,
        keys=keys,
    )


def get_sample_group_route_plain(
    group_uuid: uuid.UUID = RANDOM_UUID,
    route_name: str = 'rb-gateway',
    project_uuid: uuid.UUID = SAMPLE_PROJECT_UUID,
    project_name: str = 'my-project',
) -> GroupRoute:
    return GroupRoute(
        group_uuid=group_uuid,
        route_name=route_name,
        project_uuid=project_uuid,
        project=Project(
            uuid=project_uuid,
            name=project_name,
            created_at=datetime.datetime.now(tz=UTC),
            updated_at=datetime.datetime.now(tz=UTC),
            deleted_at=None,
        ),
    )


def get_sample_group_route(
    group_uuid: uuid.UUID = RANDOM_UUID,
    route_name: str = 'rb-gateway',
    group_name: str | None = None,
    project_uuid: uuid.UUID = SAMPLE_PROJECT_UUID,
    project_name: str = 'my-project',
) -> GroupRoute:
    if group_name is None:
        group_name = f'group-{group_uuid}'

    return GroupRoute(
        group_uuid=group_uuid,
        route_name=route_name,
        project_uuid=project_uuid,
        group=get_sample_group(
            uuid=group_uuid,
            name=group_name,
            group_routes=[],
        ),
        project=Project(
            uuid=project_uuid,
            name=project_name,
            created_at=datetime.datetime.now(tz=UTC),
            updated_at=datetime.datetime.now(tz=UTC),
            deleted_at=None,
        ),
    )


def get_sample_api_key_sec(
    plain_key: str = PLAIN_KEY, hashed_key: str = HASHED_KEY
) -> ApiKeySec:
    return ApiKeySec(plain_key=plain_key, hashed_key=hashed_key)


def get_sample_key_in(name: str = 'user@domain.com') -> KeyIn:
    return KeyIn(name=name)


def get_sample_group_in(name: str = 'group') -> GroupIn:
    return GroupIn(name=name)


def get_sample_group_routes_in(
    routes_name: list[str] = ['rb-gateway'],
) -> GroupRoutesIn:
    return GroupRoutesIn(routes=routes_name)


def get_sample_key_group_in(group_uuid: uuid.UUID = RANDOM_UUID) -> KeyGroupIn:
    return KeyGroupIn(group=group_uuid)


def get_sample_keys_uuid_in(keys_uuid: list[uuid.UUID]) -> KeysUuidIn:
    return KeysUuidIn(keys=keys_uuid)


def get_sample_group_full_out(
    uuid: uuid.UUID = RANDOM_UUID, name: str = 'group'
) -> GroupFullOut:
    return GroupFullOut.from_group(get_sample_group(uuid=uuid, name=name))


def get_sample_key_out(
    uuid: uuid.UUID = RANDOM_UUID,
    name: str = 'key',
    hashed_key: str = 'hashed-key',
    api_key: str = 'sk-dummy-key',
) -> KeyOut:
    now = datetime.datetime.now(tz=UTC)
    return KeyOut(
        uuid=uuid,
        name=name,
        owner='gateway',
        metadata=None,
        hashed_key=hashed_key,
        api_key=api_key,
        created_at=str(now),
        updated_at=str(now),
    )


def get_sample_group_out(
    uuid: uuid.UUID = uuid.uuid4(), name: str = 'group'
) -> GroupOut:
    now = datetime.datetime.now(tz=UTC)
    return GroupOut(
        uuid=uuid,
        name=name,
        owner='gateway',
        metadata=None,
        created_at=str(now),
        updated_at=str(now),
    )


def get_sample_key_full_out(
    uuid: uuid.UUID = uuid.uuid4(),
    name: str = 'key',
    api_key: str = 'api-key',
    hashed_key: str = 'hashed-key',
) -> KeyFullOut:
    now = datetime.datetime.now(tz=UTC)
    return KeyFullOut(
        uuid=uuid,
        name=name,
        owner='gateway',
        metadata=None,
        api_key=api_key,
        hashed_key=hashed_key,
        created_at=str(now),
        updated_at=str(now),
        group=get_sample_group_out(),
    )


def get_sample_route_groups_in(
    groups: list[uuid.UUID] = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()],
) -> RouteGroupsIn:
    return RouteGroupsIn(groups=groups)


def get_sample_route_groups_out(
    route_name: str = 'route',
    project_name: str = 'project',
    groups: list[GroupOut] | None = None,
) -> GroupsRouteOut:
    return GroupsRouteOut(
        route_name=route_name, project_name=project_name, groups=groups
    )


def get_sample_project(
    uuid: uuid.UUID = RANDOM_UUID,
    name: str = 'my-project',
    description: str | None = None,
    served_config_uuid: uuid.UUID | None = None,
    first_served_at: datetime.datetime | None = None,
    deleted_at: datetime.datetime | None = None,
) -> Project:
    now = datetime.datetime.now(tz=UTC)
    return Project(
        uuid=uuid,
        name=name,
        description=description,
        served_config_uuid=served_config_uuid,
        created_at=now,
        updated_at=now,
        first_served_at=first_served_at,
        deleted_at=deleted_at,
    )


_UNSET = object()


def get_sample_project_config(
    project_uuid: uuid.UUID,
    slot: Slot = Slot.A,
    config_file: str | None = None,
    config_status: ConfigStatus = ConfigStatus.DRAFT,
    uuid: uuid.UUID | None = None,
    deleted_at: datetime.datetime | None = None,
    updated_at=_UNSET,
) -> ProjectConfig:
    now = datetime.datetime.now(tz=UTC)
    return ProjectConfig(
        uuid=uuid or uuid4(),
        project_uuid=project_uuid,
        slot=slot.value,
        config_file=config_file,
        config_status=config_status.value,
        created_at=now,
        updated_at=now if updated_at is _UNSET else updated_at,
        deleted_at=deleted_at,
    )


def get_sample_project_in(
    name: str = 'my-project',
    description: str | None = None,
) -> ProjectIn:
    return ProjectIn(
        name=name,
        description=description,
    )


def get_sample_config_slot_out(
    uuid: uuid.UUID = RANDOM_UUID,
    slot: Slot = Slot.A,
    config_file: str | None = None,
    config_status: ConfigStatus = ConfigStatus.DRAFT,
) -> ConfigSlotOut:
    now = datetime.datetime.now(tz=UTC)
    return ConfigSlotOut(
        uuid=uuid,
        slot=slot.value,
        config_file=config_file,
        config_status=config_status,
        created_at=str(now),
        updated_at=str(now),
    )


def get_sample_project_out(
    uuid: uuid.UUID = RANDOM_UUID,
    name: str = 'my-project',
    description: str | None = None,
    served_config_uuid: uuid.UUID | None = None,
    configs: list[ConfigSlotOut] | None = None,
) -> ProjectOut:
    now = datetime.datetime.now(tz=UTC)
    if configs is None:
        configs = [
            get_sample_config_slot_out(uuid=uuid4(), slot=Slot.A),
            get_sample_config_slot_out(uuid=uuid4(), slot=Slot.B),
        ]
    return ProjectOut(
        uuid=uuid,
        name=name,
        description=description,
        project_status=ProjectStatus.PROD
        if served_config_uuid is not None
        else ProjectStatus.DEV,
        served_config_uuid=served_config_uuid,
        configs=configs,
        created_at=str(now),
        updated_at=str(now),
    )


VALID_CONFIG_YAML = """\
chat_models:
  - model_id: mock-chat
    model: mock/gateway
    params:
      latency_ms: 150
      response_text: "mock response"
routes:
  test-route:
    chat_models:
      - mock-chat
"""


def get_sample_project_config_file_in(
    config_file: str = VALID_CONFIG_YAML,
) -> ProjectConfigFileIn:
    return ProjectConfigFileIn(config_file=config_file)


def get_sample_event(
    request_uuid: uuid.UUID | None = None,
    route_name: str = 'rb-gateway',
    timestamp: datetime.datetime = datetime.datetime(
        2025, 10, 14, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
    ),
    value: int = 1,
    event_type: str = 'RATE_LIMIT',
    api_key_uuid: uuid.UUID | None = None,
    api_key_name: str = 'fake',
    group_uuid: uuid.UUID | None = None,
    group_name: str = 'group',
    cost: float = 0.0,
    model_id: str = '',
    model_type: str = '',
    is_cached_tokens: bool = False,
    is_judge: bool = False,
    **kwargs,
) -> Event:
    # Extract known attributes for dedicated columns (support both old and new names)
    cache_type = kwargs.get('cache_type', '')
    target = kwargs.get('target', '')
    fallback = kwargs.get('fallback', '')

    # Support both old names (what tests use) and direct guardrail_* parameters
    guardrail_name = kwargs.get('name', kwargs.get('guardrail_name', ''))
    guardrail_type = kwargs.get('type', kwargs.get('guardrail_type', ''))
    guardrail_where = kwargs.get('where', kwargs.get('guardrail_where', ''))
    guardrail_params = kwargs.get('parameters', kwargs.get('guardrail_params', ''))
    guardrail_behavior = kwargs.get('behavior', kwargs.get('guardrail_behavior', ''))

    return Event(
        request_uuid=request_uuid if request_uuid else uuid.uuid4(),
        timestamp=timestamp,
        date=timestamp.date(),
        event_type=event_type,
        route_name=route_name,
        value=value,
        api_key_uuid=api_key_uuid if api_key_uuid else uuid.uuid4(),
        api_key_name=api_key_name,
        group_uuid=group_uuid if group_uuid else uuid.uuid4(),
        group_name=group_name,
        cost=cost,
        attributes=kwargs,
        model_id=model_id,
        model_type=model_type,
        is_cached_tokens=is_cached_tokens,
        cache_type=cache_type,
        target=target,
        fallback=fallback,
        guardrail_name=guardrail_name,
        guardrail_type=guardrail_type,
        guardrail_where=guardrail_where,
        guardrail_params=guardrail_params,
        guardrail_behavior=guardrail_behavior,
        is_judge=is_judge,
    )


def get_event_detail(
    timestamp: datetime.datetime = datetime.datetime(
        2025, 10, 14, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
    ),
    api_key_uuid: uuid.UUID = uuid.UUID('00000000-0000-0000-0000-000000000000'),
    route_name: str = 'route-A',
    event_type: str = 'CACHE_HIT',
    target: str | None = '',
    fallback: str | None = '',
    name: str | None = '',
    type: str | None = '',
    where: str | None = '',
    parameters: str | None = '',
    behavior: str | None = '',
    api_key_name: str = 'fake-name',
) -> EventDetails:
    return EventDetails(
        timestamp=timestamp,
        api_key_uuid=api_key_uuid,
        route_name=route_name,
        event_type=event_type,
        target=target,
        fallback=fallback,
        name=name,
        type=type,
        where=where,
        parameters=parameters,
        behavior=behavior,
        api_key_name=api_key_name,
    )


def get_sample_request_event(
    request_uuid: uuid.UUID | None = None,
    route_name: str = 'rb-gateway',
    timestamp: datetime.datetime = datetime.datetime(
        2025, 10, 14, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
    ),
    api_key_uuid: uuid.UUID | None = None,
    api_key_name: str = 'fake',
    group_uuid: uuid.UUID | None = None,
    group_name: str = 'group',
    request_type: RequestType = RequestType.CHAT_COMPLETIONS,
    request_status: RequestStatus = RequestStatus.SUCCESS,
    http_status_code: int = 200,
    duration_ms: float = 100.0,
    error_type: str = '',
    error_code: str = '',
    is_streaming: bool = False,
) -> RequestEvent:
    return RequestEvent(
        request_uuid=request_uuid if request_uuid else uuid.uuid4(),
        timestamp=timestamp,
        date=timestamp.date(),
        route_name=route_name,
        api_key_uuid=api_key_uuid if api_key_uuid else uuid.uuid4(),
        api_key_name=api_key_name,
        group_uuid=group_uuid if group_uuid else uuid.uuid4(),
        group_name=group_name,
        request_type=request_type.value,
        request_status=request_status.value,
        http_status_code=http_status_code,
        duration_ms=duration_ms,
        error_type=error_type,
        error_code=error_code,
        is_streaming=is_streaming,
    )


def get_sample_otel_span(
    timestamp: datetime.datetime,
    trace_id: str = 'abc123',
    span_id: str = 'span001',
    span_name: str = 'invoke',
    service_name: str = 'radicalbit-ai-gateway',
    duration_ns: int = 100_000_000,
    status_code: str = 'Unset',
    parent_span_id: str | None = None,
    span_attributes: dict[str, str] | None = None,
    status_message: str = '',
    trace_state: str = '',
    span_kind: str = 'internal',
    resource_attributes: dict[str, str] | None = None,
    scope_name: str = '',
    scope_version: str = '',
    events_timestamp: list | None = None,
    events_name: list | None = None,
    events_attributes: list | None = None,
):
    """Create a sample OtelTraces instance for testing."""
    attrs = {_TEST_PROJECT_UUID_KEY: str(TEST_PROJECT_UUID)}
    if span_attributes:
        attrs.update(span_attributes)
    return OtelTraces(
        timestamp=timestamp,
        trace_id=trace_id,
        span_id=span_id,
        span_name=span_name,
        service_name=service_name,
        span_attributes=attrs,
        duration=duration_ns,
        status_code=status_code,
        parent_span_id=parent_span_id or '',
        status_message=status_message,
        trace_state=trace_state,
        span_kind=span_kind,
        resource_attributes=resource_attributes or {},
        scope_name=scope_name,
        scope_version=scope_version,
        events_timestamp=events_timestamp,
        events_name=events_name,
        events_attributes=events_attributes,
    )
