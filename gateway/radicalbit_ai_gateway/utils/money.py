# Budgets are stored in billionths of a dollar (BUDGET_MULTIPLIER): nine
# decimals show any value that can be saved
_MAX_DECIMALS = 9
_MIN_DECIMALS = 2


def format_usd(value: float) -> str:
    """Format an amount in USD for a message, never in exponent notation.

    Args:
        value: The amount in USD, e.g. 2e-05.

    Returns:
        The amount with two to nine decimals, e.g. '$0.00002' or '$1,500.00'.

    """
    integer, _, decimals = f'{value:,.{_MAX_DECIMALS}f}'.partition('.')
    decimals = decimals.rstrip('0').ljust(_MIN_DECIMALS, '0')
    return f'${integer}.{decimals}'
