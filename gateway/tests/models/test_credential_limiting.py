import uuid

import pytest

from radicalbit_ai_gateway.models.credential_limiting import (
    CredentialLimitCategory,
    CredentialLimitIn,
    CredentialLimitOut,
    CredentialLimitsIn,
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
    limit_in = CredentialLimitIn(category=category, window_size='1 day', value=10)
    assert limit_in.category == category
    assert limit_in.algorithm == LimitingAlgorithmType.FIXED_WINDOW


def test_invalid_window_size_for_aligned_fixed_window_rejected():
    with pytest.raises(ValueError, match='not allowed for ALIGNED_FIXED_WINDOW'):
        CredentialLimitIn(
            category=CredentialLimitCategory.BUDGET,
            algorithm=LimitingAlgorithmType.ALIGNED_FIXED_WINDOW,
            window_size='3 days',
            value=10,
        )


def test_value_must_be_positive():
    with pytest.raises(ValueError):
        CredentialLimitIn(
            category=CredentialLimitCategory.BUDGET, window_size='1 day', value=0
        )


def test_to_key_limit_maps_fields():
    key_uuid = uuid.uuid4()
    limit_in = CredentialLimitIn(
        category=CredentialLimitCategory.BUDGET, window_size='1 day', value=10
    )
    key_limit = limit_in.to_key_limit(key_uuid)
    assert key_limit.key_uuid == key_uuid
    assert key_limit.category == 'budget'
    assert key_limit.algorithm == 'FIXED_WINDOW'
    assert key_limit.window_size == '1 day'
    assert key_limit.max_value == 10


def test_limits_in_requires_at_least_one():
    with pytest.raises(ValueError):
        CredentialLimitsIn(limits=[])


def test_limits_in_accepts_multiple_different_categories():
    limits_in = CredentialLimitsIn(
        limits=[
            CredentialLimitIn(
                category=CredentialLimitCategory.RATE, window_size='1 hour', value=10
            ),
            CredentialLimitIn(
                category=CredentialLimitCategory.BUDGET, window_size='1 day', value=5
            ),
        ]
    )
    assert len(limits_in.limits) == 2


def test_limits_in_rejects_duplicate_within_batch():
    with pytest.raises(ValueError, match='Duplicate limit in request'):
        CredentialLimitsIn(
            limits=[
                CredentialLimitIn(
                    category=CredentialLimitCategory.BUDGET,
                    window_size='1 day',
                    value=10,
                ),
                CredentialLimitIn(
                    category=CredentialLimitCategory.BUDGET,
                    window_size='1 day',
                    value=20,
                ),
            ]
        )


def test_limits_in_allows_same_category_with_different_window():
    limits_in = CredentialLimitsIn(
        limits=[
            CredentialLimitIn(
                category=CredentialLimitCategory.BUDGET, window_size='1 day', value=1
            ),
            CredentialLimitIn(
                category=CredentialLimitCategory.BUDGET, window_size='1 month', value=15
            ),
        ]
    )
    assert len(limits_in.limits) == 2


def test_to_key_limits_maps_all_entries():
    key_uuid = uuid.uuid4()
    limits_in = CredentialLimitsIn(
        limits=[
            CredentialLimitIn(
                category=CredentialLimitCategory.RATE, window_size='1 hour', value=10
            ),
            CredentialLimitIn(
                category=CredentialLimitCategory.BUDGET, window_size='1 day', value=5
            ),
        ]
    )
    key_limits = limits_in.to_key_limits(key_uuid)
    assert len(key_limits) == 2
    assert all(kl.key_uuid == key_uuid for kl in key_limits)
    assert {kl.category for kl in key_limits} == {'request_rate', 'budget'}


def test_credential_limit_out_round_trip():
    key_uuid = uuid.uuid4()
    limit_in = CredentialLimitIn(
        category=CredentialLimitCategory.RATE, window_size='1 minute', value=100
    )
    key_limit = limit_in.to_key_limit(key_uuid)
    # `uuid` has a column default applied at flush time by SQLAlchemy, not at
    # construction time, so set it explicitly to mimic an already-persisted row.
    key_limit.uuid = uuid.uuid4()
    limit_out = CredentialLimitOut.from_key_limit(key_limit)
    assert limit_out.category == CredentialLimitCategory.RATE
    assert limit_out.algorithm == LimitingAlgorithmType.FIXED_WINDOW
    assert limit_out.window_size == '1 minute'
    assert limit_out.value == 100
