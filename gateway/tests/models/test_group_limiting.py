import uuid

import pytest

from radicalbit_ai_gateway.models.credential_limiting import CredentialLimitCategory
from radicalbit_ai_gateway.models.group_limiting import (
    GroupLimitIn,
    GroupLimitOut,
    GroupLimitsIn,
)
from radicalbit_ai_gateway.models.limiting import LimitingAlgorithmType


@pytest.mark.parametrize(
    'category',
    [
        CredentialLimitCategory.RATE,
        CredentialLimitCategory.TOKEN_INPUT,
        CredentialLimitCategory.TOKEN_OUTPUT,
        CredentialLimitCategory.BUDGET,
    ],
)
def test_valid_limit_for_each_category(category):
    limit_in = GroupLimitIn(category=category, window_size='1 day', value=10)
    assert limit_in.category == category
    assert limit_in.algorithm == LimitingAlgorithmType.FIXED_WINDOW


def test_invalid_window_size_for_aligned_fixed_window_rejected():
    with pytest.raises(ValueError, match='not allowed for ALIGNED_FIXED_WINDOW'):
        GroupLimitIn(
            category=CredentialLimitCategory.BUDGET,
            algorithm=LimitingAlgorithmType.ALIGNED_FIXED_WINDOW,
            window_size='3 days',
            value=10,
        )


def test_value_must_be_positive():
    with pytest.raises(ValueError):
        GroupLimitIn(
            category=CredentialLimitCategory.BUDGET, window_size='1 day', value=0
        )


def test_to_group_limit_maps_fields():
    group_uuid = uuid.uuid4()
    limit_in = GroupLimitIn(
        category=CredentialLimitCategory.BUDGET, window_size='1 day', value=10
    )
    group_limit = limit_in.to_group_limit(group_uuid)
    assert group_limit.group_uuid == group_uuid
    assert group_limit.category == 'budget'
    assert group_limit.algorithm == 'FIXED_WINDOW'
    assert group_limit.window_size == '1 day'
    assert group_limit.max_value == 10


def test_limits_in_requires_at_least_one():
    with pytest.raises(ValueError):
        GroupLimitsIn(limits=[])


def test_limits_in_rejects_duplicate_within_batch():
    with pytest.raises(ValueError, match='Duplicate limit in request'):
        GroupLimitsIn(
            limits=[
                GroupLimitIn(
                    category=CredentialLimitCategory.BUDGET,
                    window_size='1 day',
                    value=10,
                ),
                GroupLimitIn(
                    category=CredentialLimitCategory.BUDGET,
                    window_size='1 day',
                    value=20,
                ),
            ]
        )


def test_limits_in_allows_same_category_with_different_window():
    limits_in = GroupLimitsIn(
        limits=[
            GroupLimitIn(
                category=CredentialLimitCategory.BUDGET, window_size='1 day', value=1
            ),
            GroupLimitIn(
                category=CredentialLimitCategory.BUDGET, window_size='1 month', value=15
            ),
        ]
    )
    assert len(limits_in.limits) == 2


def test_to_group_limits_maps_all_entries():
    group_uuid = uuid.uuid4()
    limits_in = GroupLimitsIn(
        limits=[
            GroupLimitIn(
                category=CredentialLimitCategory.RATE, window_size='1 hour', value=10
            ),
            GroupLimitIn(
                category=CredentialLimitCategory.BUDGET, window_size='1 day', value=5
            ),
        ]
    )
    group_limits = limits_in.to_group_limits(group_uuid)
    assert len(group_limits) == 2
    assert all(gl.group_uuid == group_uuid for gl in group_limits)
    assert {gl.category for gl in group_limits} == {'request_rate', 'budget'}


def test_group_limit_out_round_trip():
    group_uuid = uuid.uuid4()
    limit_in = GroupLimitIn(
        category=CredentialLimitCategory.RATE, window_size='1 minute', value=100
    )
    group_limit = limit_in.to_group_limit(group_uuid)
    group_limit.uuid = uuid.uuid4()
    limit_out = GroupLimitOut.from_group_limit(group_limit)
    assert limit_out.category == CredentialLimitCategory.RATE
    assert limit_out.algorithm == LimitingAlgorithmType.FIXED_WINDOW
    assert limit_out.window_size == '1 minute'
    assert limit_out.value == 100
