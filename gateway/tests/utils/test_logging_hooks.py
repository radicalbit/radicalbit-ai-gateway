import logging

import pytest

from radicalbit_ai_gateway.utils import logging_hooks
from radicalbit_ai_gateway.utils.logging_hooks import (
    apply_log_filters,
    get_log_filters,
    register_log_filter,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    logging_hooks._log_filters.clear()
    yield
    logging_hooks._log_filters.clear()


class _DropAll(logging.Filter):
    def filter(self, record):
        return False


def test_register_and_get_returns_in_order():
    f1, f2 = _DropAll(), _DropAll()
    register_log_filter(f1)
    register_log_filter(f2)

    assert get_log_filters() == [f1, f2]


def test_get_returns_a_copy():
    register_log_filter(_DropAll())
    get_log_filters().clear()

    assert len(get_log_filters()) == 1


def test_apply_attaches_registered_filters_to_logger():
    f = _DropAll()
    register_log_filter(f)
    logger = logging.getLogger('test-apply-log-filters')

    apply_log_filters(logger)

    assert f in logger.filters
    # The attached filter drops records on this logger.
    assert logger.filter(logging.makeLogRecord({})) is False
