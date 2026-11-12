import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID

from fastapi_pagination import Page, Params
import pytest

from radicalbit_ai_gateway.db.dao.event_dao import EventDAO
from radicalbit_ai_gateway.db.models.event import InvocationChartDataPoint
from radicalbit_ai_gateway.models.mcp_usage_dto import (
    McpKeyUsageDTO,
    McpServerChartDataDTO,
    McpServerChartDataSeriesDTO,
)
from radicalbit_ai_gateway.services.group_service import GroupService
from radicalbit_ai_gateway.services.key_service import KeyService
from radicalbit_ai_gateway.services.mcp_usage_service import McpUsageService

PROJECT_UUID = UUID('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
KEY_UUID = UUID('660e8400-e29b-41d4-a716-446655440003')
GROUP_UUID = UUID('550e8400-e29b-41d4-a716-446655440003')

LAST_CALL = datetime.datetime(2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc)

BUCKET_0 = datetime.datetime(2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc)
BUCKET_1 = BUCKET_0 + datetime.timedelta(hours=1)
BUCKET_2 = BUCKET_0 + datetime.timedelta(hours=2)
AXIS = [int(b.timestamp()) for b in (BUCKET_0, BUCKET_1, BUCKET_2)]

# The two chart endpoints share the bucket-to-series build: every chart test
# runs against both, through the DAO method each one reads.
GROUPED = 'get_mcp_server_chart_data'
BY_ENTITY = 'get_mcp_server_chart_data_by_entity'
CHARTS = pytest.mark.parametrize('method', [GROUPED, BY_ENTITY])


def row(key_name: str = 'my-key') -> SimpleNamespace:
    """Stand in for the DAO row, which is a SQLAlchemy `Row`."""
    return SimpleNamespace(
        key_uuid=KEY_UUID,
        key_name=key_name,
        group_uuid=GROUP_UUID,
        group_name='my-group',
        counter=3,
        last_call=LAST_CALL,
    )


def point(bucket, group_by_value: str, value: int) -> InvocationChartDataPoint:
    return InvocationChartDataPoint(
        bucket=bucket, group_by_value=group_by_value, value=value
    )


def _service() -> McpUsageService:
    return McpUsageService(
        event_dao=MagicMock(spec_set=EventDAO),
        key_service=MagicMock(spec_set=KeyService),
        group_service=MagicMock(spec_set=GroupService),
    )


def chart(service, method, points, **kwargs):
    setattr(service.event_dao, method, MagicMock(return_value=points))
    entity = {'group_by': 'services', 'entity_value': 'files'}
    args = {
        'project_uuid': PROJECT_UUID,
        'route_names': None,
        '_from': BUCKET_0,
        '_to': BUCKET_2,
        'tags': None,
        **(entity if method == BY_ENTITY else {}),
        **kwargs,
    }
    return getattr(service, method)(**args)


def test_key_usage_rows_become_dtos_in_the_dao_page_envelope():
    service = _service()
    params = Params(page=2, size=2)
    service.event_dao.get_mcp_key_usage_paginated = MagicMock(
        return_value=Page.create([row(), row(key_name='other')], params, total=7)
    )

    res = service.get_mcp_key_usage(
        project_uuid=PROJECT_UUID,
        route_names=None,
        _from=None,
        _to=None,
        params=params,
    )

    dto = McpKeyUsageDTO(
        key_name='my-key',
        key_uuid=KEY_UUID,
        group_name='my-group',
        group_uuid=GROUP_UUID,
        counter=3,
        last_call=1736330400,
    )
    assert res == Page.create(
        [dto, dto.model_copy(update={'key_name': 'other'})], params, total=7
    )
    assert (res.page, res.size, res.pages) == (2, 2, 4)


def test_key_usage_passes_every_filter_to_the_dao():
    service = _service()
    params = Params(page=3, size=10)
    _to = LAST_CALL + datetime.timedelta(hours=1)
    service.event_dao.get_mcp_key_usage_paginated = MagicMock(
        return_value=Page.create([], params, total=0)
    )

    res = service.get_mcp_key_usage(
        project_uuid=PROJECT_UUID,
        route_names=['agents', 'chat'],
        _from=LAST_CALL,
        _to=_to,
        params=params,
        tags=['env=prod'],
    )

    assert res == Page.create([], params, total=0)
    service.event_dao.get_mcp_key_usage_paginated.assert_called_once_with(
        project_uuid=PROJECT_UUID,
        route_names=['agents', 'chat'],
        _from=LAST_CALL,
        _to=_to,
        params=params,
        tags=['env=prod'],
    )


@pytest.mark.parametrize(
    ('method', 'group_by', 'entity_value', 'entity_kwargs'),
    [
        (GROUPED, 'keys', None, {'group_by': 'keys'}),
        (
            BY_ENTITY,
            'services',
            'files',
            {'entity_column': 'MCP_ALIAS', 'series_column': 'MCP_TARGET'},
        ),
        (
            BY_ENTITY,
            'groups',
            str(GROUP_UUID),
            {'entity_column': 'GROUP_UUID', 'series_column': None},
        ),
        (
            BY_ENTITY,
            'keys',
            str(KEY_UUID),
            {'entity_column': 'API_KEY_UUID', 'series_column': None},
        ),
    ],
)
def test_a_quiet_window_is_an_empty_chart_and_the_dao_gets_every_filter(
    method, group_by, entity_value, entity_kwargs
):
    """A ten-day range reads by days, and the DAO is asked for that bucket."""
    service = _service()
    _from = BUCKET_0 - datetime.timedelta(days=10)
    extra = {'entity_value': entity_value} if entity_value else {}

    res = chart(
        service,
        method,
        [],
        route_names=['agents'],
        _from=_from,
        _to=BUCKET_0,
        group_by=group_by,
        tags=['env=prod'],
        **extra,
    )

    assert res == McpServerChartDataDTO(
        granularity='days', timestamp=[], data=[], total=0
    )
    getattr(service.event_dao, method).assert_called_once_with(
        project_uuid=PROJECT_UUID,
        route_names=['agents'],
        _from=_from,
        _to=BUCKET_0,
        granularity='days',
        timezone_offset_seconds=0,
        tags=['env=prod'],
        **extra,
        **entity_kwargs,
    )


@CHARTS
def test_one_zero_filled_series_per_alias_on_a_shared_axis(method):
    """Server aliases, or a server's targets, are their own names and carry
    no uuid. An unresolved alias or untargeted call is the empty name.
    """
    service = _service()
    res = chart(
        service,
        method,
        [
            point(BUCKET_0, 'read_file', 2),
            point(BUCKET_0, '', 3),
            point(BUCKET_0, 'write_file', 1),
            point(BUCKET_2, 'read_file', 4),
        ],
        group_by='services',
    )

    assert res == McpServerChartDataDTO(
        granularity='hours',
        timestamp=AXIS,
        data=[
            McpServerChartDataSeriesDTO(name='', uuid=None, data=[3, 0, 0]),
            McpServerChartDataSeriesDTO(name='read_file', uuid=None, data=[2, 0, 4]),
            McpServerChartDataSeriesDTO(name='write_file', uuid=None, data=[1, 0, 0]),
        ],
        total=10,
    )
    assert all(isinstance(v, int) for s in res.data for v in s.data)
    assert isinstance(res.total, int)


@CHARTS
@pytest.mark.parametrize(
    ('group_by', 'uuid', 'names', 'name'),
    [
        ('keys', KEY_UUID, {KEY_UUID: 'agent-key'}, 'agent-key'),
        ('keys', KEY_UUID, {}, f'Deleted Key ({str(KEY_UUID)[:8]})'),
        ('groups', GROUP_UUID, {GROUP_UUID: 'retail'}, 'retail'),
        ('groups', GROUP_UUID, {}, f'Deleted Group ({str(GROUP_UUID)[:8]})'),
    ],
)
def test_a_key_or_group_is_named_and_carries_its_uuid(
    method, group_by, uuid, names, name
):
    service = _service()
    lookup = service.key_service if group_by == 'keys' else service.group_service
    lookup.get_names_by_uuids = MagicMock(return_value=names)
    extra = {'entity_value': str(uuid)} if method == BY_ENTITY else {}

    res = chart(
        service, method, [point(BUCKET_0, str(uuid), 5)], group_by=group_by, **extra
    )

    assert res == McpServerChartDataDTO(
        granularity='hours',
        timestamp=AXIS,
        data=[McpServerChartDataSeriesDTO(name=name, uuid=uuid, data=[5, 0, 0])],
        total=5,
    )
    lookup.get_names_by_uuids.assert_called_once_with([uuid])


def test_two_groups_sharing_a_name_stay_two_series():
    service = _service()
    other = UUID('550e8400-e29b-41d4-a716-446655440009')
    service.group_service.get_names_by_uuids = MagicMock(
        return_value={GROUP_UUID: 'retail', other: 'retail'}
    )

    res = chart(
        service,
        GROUPED,
        [point(BUCKET_0, str(other), 3), point(BUCKET_0, str(GROUP_UUID), 2)],
        group_by='groups',
    )

    assert res == McpServerChartDataDTO(
        granularity='hours',
        timestamp=AXIS,
        data=[
            McpServerChartDataSeriesDTO(name='retail', uuid=GROUP_UUID, data=[2, 0, 0]),
            McpServerChartDataSeriesDTO(name='retail', uuid=other, data=[3, 0, 0]),
        ],
        total=5,
    )
