import uuid

from pydantic import ValidationError
import pytest

from radicalbit_ai_gateway.models.credential_limiting import CredentialLimitCategory
from radicalbit_ai_gateway.models.group_limiting import GroupLimitsIn, GroupLimitSkipIn
from radicalbit_ai_gateway.models.limiting import LimitingAlgorithmType


def _limit(window_size='1 day', algorithm='FIXED_WINDOW', category='budget'):
    return {
        'category': category,
        'algorithm': algorithm,
        'windowSize': window_size,
        'value': 10,
    }


def test_skip_defaults_to_empty():
    limits_in = GroupLimitsIn.model_validate({'limits': [_limit()]})
    assert limits_in.skip == []


def test_limits_require_at_least_one():
    with pytest.raises(ValidationError):
        GroupLimitsIn.model_validate({'limits': []})


def test_window_is_canonicalised_like_a_credential_limit():
    limits_in = GroupLimitsIn.model_validate({'limits': [_limit('60 seconds')]})
    assert limits_in.limits[0].window_size == '1 minute'


def test_window_outside_the_allowed_list_is_refused_on_window_size():
    with pytest.raises(ValidationError) as exc_info:
        GroupLimitsIn.model_validate({'limits': [_limit('7 minutes')]})
    [error] = exc_info.value.errors()
    assert error['loc'] == ('limits', 0, 'windowSize')


def test_duplicates_in_another_unit_are_refused():
    with pytest.raises(ValidationError, match='Duplicate limit'):
        GroupLimitsIn.model_validate(
            {'limits': [_limit('1 minute'), _limit('60 seconds')]}
        )


def test_skip_window_is_canonicalised_so_it_matches_the_saved_limit():
    key_uuid = uuid.uuid4()
    limits_in = GroupLimitsIn.model_validate(
        {
            'limits': [_limit('1 minute')],
            'skip': [
                {
                    'keyUuid': str(key_uuid),
                    'category': 'budget',
                    'algorithm': 'FIXED_WINDOW',
                    'windowSize': 60,
                }
            ],
        }
    )
    assert limits_in.skip == [
        GroupLimitSkipIn(
            key_uuid=key_uuid,
            category=CredentialLimitCategory.BUDGET,
            algorithm=LimitingAlgorithmType.FIXED_WINDOW,
            window_size='1 minute',
        )
    ]
