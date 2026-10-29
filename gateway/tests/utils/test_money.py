import pytest

from radicalbit_ai_gateway.utils.money import format_usd


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        (2e-05, '$0.00002'),
        (40, '$40.00'),
        (1500, '$1,500.00'),
        (0.5, '$0.50'),
        (12.345, '$12.345'),
        (1e-09, '$0.000000001'),
    ],
)
def test_format_usd_never_uses_exponent(value, expected):
    assert format_usd(value) == expected
