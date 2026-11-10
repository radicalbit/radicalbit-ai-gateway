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


def _limit(category, window_size, value):
    return CredentialLimitIn(category=category, window_size=window_size, value=value)


@pytest.mark.parametrize(
    'limits',
    [
        pytest.param(
            [
                _limit(CredentialLimitCategory.RATE, '1 hour', 10),
                _limit(CredentialLimitCategory.BUDGET, '1 day', 5),
            ],
            id='different-categories',
        ),
        pytest.param(
            [
                _limit(CredentialLimitCategory.BUDGET, '1 day', 1),
                _limit(CredentialLimitCategory.BUDGET, '1 month', 15),
            ],
            id='same-category-different-window',
        ),
    ],
)
def test_limits_in_accepts_distinct_limits(limits):
    assert CredentialLimitsIn(limits=limits).limits == limits


@pytest.mark.parametrize(
    'limits',
    [
        pytest.param(
            [
                _limit(CredentialLimitCategory.BUDGET, '1 day', 10),
                _limit(CredentialLimitCategory.BUDGET, '1 day', 20),
            ],
            id='same-window',
        ),
        pytest.param(
            [
                _limit(CredentialLimitCategory.RATE, '60 seconds', 10),
                _limit(CredentialLimitCategory.RATE, '1 minute', 20),
            ],
            id='same-window-written-differently',
        ),
    ],
)
def test_limits_in_rejects_duplicate_within_batch(limits):
    with pytest.raises(ValueError, match='Duplicate limit in request'):
        CredentialLimitsIn(limits=limits)


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


@pytest.mark.parametrize(
    ('window_size', 'canonical'),
    [
        ('60 seconds', '1 minute'),
        ('24 hours', '1 day'),
        ('1 Hours', '1 hour'),
        ('30 days', '1 month'),
        (300, '5 minutes'),
        (604800, '1 week'),
        (60.0, '1 minute'),  # a whole float is read as seconds
    ],
)
def test_window_size_is_canonicalised(window_size, canonical):
    limit_in = CredentialLimitIn(
        category=CredentialLimitCategory.RATE, window_size=window_size, value=10
    )
    assert limit_in.window_size == canonical


@pytest.mark.parametrize('window_size', ['1 week', '1 month', '12 hours'])
def test_fixed_window_accepts_windows_of_the_list(window_size):
    limit_in = CredentialLimitIn(
        category=CredentialLimitCategory.RATE, window_size=window_size, value=10
    )
    assert limit_in.window_size == window_size


FIXED = LimitingAlgorithmType.FIXED_WINDOW
ALIGNED = LimitingAlgorithmType.ALIGNED_FIXED_WINDOW


@pytest.mark.parametrize(
    ('algorithm', 'window_size', 'match'),
    [
        pytest.param(
            FIXED, '7 hours', 'not allowed for FIXED_WINDOW', id='fixed-7-hours'
        ),
        pytest.param(
            FIXED, '3 days', 'not allowed for FIXED_WINDOW', id='fixed-3-days'
        ),
        pytest.param(
            FIXED, '2 weeks', 'not allowed for FIXED_WINDOW', id='fixed-2-weeks'
        ),
        pytest.param(
            FIXED, '45 seconds', 'not allowed for FIXED_WINDOW', id='fixed-45-seconds'
        ),
        pytest.param(
            ALIGNED,
            '3 days',
            'not allowed for ALIGNED_FIXED_WINDOW',
            id='aligned-3-days',
        ),
        pytest.param(
            ALIGNED,
            '1 week',
            'not allowed for ALIGNED_FIXED_WINDOW',
            id='aligned-1-week',
        ),
        pytest.param(
            ALIGNED,
            '1 month',
            'not allowed for ALIGNED_FIXED_WINDOW',
            id='aligned-1-month',
        ),
        pytest.param(
            FIXED, '0 seconds', 'must be longer than 0', id='zero-seconds-string'
        ),
        pytest.param(FIXED, 0, 'must be longer than 0', id='zero-int'),
        pytest.param(FIXED, -60, 'must be longer than 0', id='negative'),
        pytest.param(FIXED, 60.5, 'whole number of seconds', id='fractional-float'),
        pytest.param(FIXED, True, 'whole number of seconds', id='bool'),
    ],
)
def test_invalid_window_is_rejected(algorithm, window_size, match):
    with pytest.raises(ValueError, match=match):
        CredentialLimitIn(
            category=CredentialLimitCategory.RATE,
            algorithm=algorithm,
            window_size=window_size,
            value=10,
        )
