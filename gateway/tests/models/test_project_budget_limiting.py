import uuid

import pytest

from radicalbit_ai_gateway.models.limiting import LimitingAlgorithmType
from radicalbit_ai_gateway.models.project_budget_limiting import (
    ProjectBudgetLimitIn,
    ProjectBudgetLimitOut,
    ProjectBudgetLimitsIn,
)


def test_valid_limit():
    limit_in = ProjectBudgetLimitIn(window_size='1 day', value=10)
    assert limit_in.algorithm == LimitingAlgorithmType.FIXED_WINDOW
    assert limit_in.window_size == '1 day'
    assert limit_in.value == 10


def test_to_project_budget_limit_maps_fields():
    project_uuid = uuid.uuid4()
    limit_in = ProjectBudgetLimitIn(window_size='1 day', value=10)
    project_budget_limit = limit_in.to_project_budget_limit(project_uuid)
    assert project_budget_limit.project_uuid == project_uuid
    assert project_budget_limit.algorithm == 'FIXED_WINDOW'
    assert project_budget_limit.window_size == '1 day'
    assert project_budget_limit.max_value == 10


def test_limits_in_requires_at_least_one():
    with pytest.raises(ValueError):
        ProjectBudgetLimitsIn(limits=[])


@pytest.mark.parametrize(
    'windows',
    [
        pytest.param(['1 day', '1 day'], id='same-window'),
        pytest.param(['24 hours', '1 day'], id='same-window-written-differently'),
    ],
)
def test_limits_in_rejects_duplicate_within_batch(windows):
    with pytest.raises(ValueError, match='Duplicate limit in request'):
        ProjectBudgetLimitsIn(
            limits=[
                ProjectBudgetLimitIn(window_size=window, value=value)
                for value, window in enumerate(windows, start=1)
            ]
        )


def test_limits_in_allows_different_windows():
    limits_in = ProjectBudgetLimitsIn(
        limits=[
            ProjectBudgetLimitIn(window_size='1 day', value=1),
            ProjectBudgetLimitIn(window_size='1 month', value=15),
        ]
    )
    assert len(limits_in.limits) == 2


def test_to_project_budget_limits_maps_all_entries():
    project_uuid = uuid.uuid4()
    limits_in = ProjectBudgetLimitsIn(
        limits=[
            ProjectBudgetLimitIn(window_size='1 day', value=1),
            ProjectBudgetLimitIn(window_size='1 month', value=15),
        ]
    )
    project_budget_limits = limits_in.to_project_budget_limits(project_uuid)
    assert len(project_budget_limits) == 2
    assert all(pbl.project_uuid == project_uuid for pbl in project_budget_limits)
    assert {pbl.window_size for pbl in project_budget_limits} == {'1 day', '1 month'}


def test_project_budget_limit_out_round_trip():
    project_uuid = uuid.uuid4()
    limit_in = ProjectBudgetLimitIn(window_size='1 minute', value=100)
    project_budget_limit = limit_in.to_project_budget_limit(project_uuid)
    # `uuid` has a column default applied at flush time by SQLAlchemy, not at
    # construction time, so set it explicitly to mimic an already-persisted row.
    project_budget_limit.uuid = uuid.uuid4()
    limit_out = ProjectBudgetLimitOut.from_project_budget_limit(project_budget_limit)
    assert limit_out.algorithm == LimitingAlgorithmType.FIXED_WINDOW
    assert limit_out.window_size == '1 minute'
    assert limit_out.value == 100


@pytest.mark.parametrize(
    ('window_size', 'canonical'),
    [('24 hours', '1 day'), ('30 days', '1 month'), (3600, '1 hour')],
)
def test_window_size_is_canonicalised(window_size, canonical):
    limit_in = ProjectBudgetLimitIn(window_size=window_size, value=10)
    assert limit_in.window_size == canonical


@pytest.mark.parametrize(
    ('kwargs', 'match'),
    [
        pytest.param(
            {'window_size': '7 hours'}, 'not allowed for FIXED_WINDOW', id='7-hours'
        ),
        pytest.param(
            {'window_size': '3 days'}, 'not allowed for FIXED_WINDOW', id='3-days'
        ),
        pytest.param(
            {'window_size': '0 seconds'}, 'must be longer than 0', id='zero-window'
        ),
        pytest.param(
            {
                'algorithm': LimitingAlgorithmType.ALIGNED_FIXED_WINDOW,
                'window_size': '3 days',
            },
            'not allowed for ALIGNED_FIXED_WINDOW',
            id='aligned-3-days',
        ),
        pytest.param({'window_size': '1 day', 'value': 0}, None, id='zero-value'),
    ],
)
def test_invalid_limit_rejected(kwargs, match):
    with pytest.raises(ValueError, match=match):
        ProjectBudgetLimitIn(**{'value': 10, **kwargs})
