import pytest

from radicalbit_ai_gateway.models.limiting import Limiting, LimitingAlgorithmType


@pytest.mark.parametrize(
    ('window_size_input', 'expected_window_size_attr'),
    [
        (60, 60),
        ('30 second', '30 second'),
        ('30 seconds', '30 seconds'),
        ('1 minutes', '1 minutes'),
        ('1 minute', '1 minute'),
        ('2 hour', '2 hour'),
    ],
)
def test_init_valid_window_size(window_size_input, expected_window_size_attr):
    limiting_instance = Limiting(window_size=window_size_input)
    assert limiting_instance.window_size == expected_window_size_attr


@pytest.mark.parametrize(
    ('window_size_input', 'expected_window_size_attr'),
    [
        ('2 h', '2 hour'),
        ('2 min', '2 hour'),
    ],
)
def test_init_wrong_window_size(window_size_input, expected_window_size_attr):
    with pytest.raises(ValueError):
        _ = Limiting(window_size=window_size_input)


@pytest.mark.parametrize(
    'kwargs',
    [
        pytest.param(
            {'max_tokens': 1000, 'max_requests': 50}, id='tokens-and-requests'
        ),
        pytest.param(
            {'max_tokens': 1000, 'max_duration_seconds': 60}, id='tokens-and-duration'
        ),
    ],
)
def test_only_one_max_can_be_set(kwargs):
    with pytest.raises(
        ValueError,
        match=r'Only one of max_requests, max_tokens, max_budget, or '
        r'max_duration_seconds can be set.',
    ):
        Limiting(**kwargs)


def test_max_duration_seconds_alone_is_valid():
    config = Limiting(max_duration_seconds=300)
    assert config.max_duration_seconds == 300


@pytest.mark.parametrize(
    ('kwargs', 'max_budget', 'max_budget_in_units'),
    [
        pytest.param({'max_budget': 1.5}, 1.5, 1_500_000_000, id='float-budget'),
        pytest.param({}, None, None, id='no-budget'),
    ],
)
def test_max_budget_in_units_is_computed(kwargs, max_budget, max_budget_in_units):
    """max_budget stays a float and max_budget_in_units is derived from it."""
    config = Limiting(**kwargs)
    assert config.max_budget == max_budget
    assert config.max_budget_in_units == max_budget_in_units


class TestAlignedFixedWindowValidation:
    """Tests for ALIGNED_FIXED_WINDOW window_size validation."""

    @pytest.mark.parametrize(
        'size',
        [
            '1 minute',
            '5 minutes',
            '10 minutes',
            '15 minutes',
            '30 minutes',
            '1 hour',
            '2 hours',
            '3 hours',
            '4 hours',
            '6 hours',
            '8 hours',
            '12 hours',
            '1 day',
        ],
    )
    def test_valid_window_sizes_allowed(self, size):
        """Valid sizes should be accepted."""
        limiting = Limiting(
            algorithm=LimitingAlgorithmType.ALIGNED_FIXED_WINDOW, window_size=size
        )
        assert limiting.window_size == size

    @pytest.mark.parametrize(
        'size',
        [
            pytest.param('3 days', id='multi-day'),
            pytest.param('7 minutes', id='non-divisor'),
            pytest.param('1 month', id='variable-month-length'),
        ],
    )
    def test_invalid_window_sizes_rejected(self, size):
        with pytest.raises(ValueError, match='not allowed for ALIGNED_FIXED_WINDOW'):
            Limiting(
                algorithm=LimitingAlgorithmType.ALIGNED_FIXED_WINDOW, window_size=size
            )

    def test_fixed_window_allows_any_size(self):
        """FIXED_WINDOW should still allow any valid window size."""
        limiting = Limiting(
            algorithm=LimitingAlgorithmType.FIXED_WINDOW, window_size='3 days'
        )
        assert limiting.window_size == '3 days'

    def test_error_message_lists_allowed_sizes(self):
        """Error message should show allowed sizes."""
        with pytest.raises(ValueError) as exc_info:
            Limiting(
                algorithm=LimitingAlgorithmType.ALIGNED_FIXED_WINDOW,
                window_size='3 days',
            )
        msg = str(exc_info.value)
        assert '1 minute' in msg or '1 day' in msg
