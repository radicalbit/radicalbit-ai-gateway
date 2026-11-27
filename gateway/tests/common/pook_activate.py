"""``pook.activate`` with a type: pook leaves the decorator unannotated, so
the test it decorates would lose its signature.
"""

from collections.abc import Awaitable, Callable
from typing import ParamSpec, TypeVar

import pook

P = ParamSpec('P')
R = TypeVar('R')


def pook_activate(test: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Run the async ``test`` with pook on, as ``@pook.activate`` does."""
    return pook.activate(test)
