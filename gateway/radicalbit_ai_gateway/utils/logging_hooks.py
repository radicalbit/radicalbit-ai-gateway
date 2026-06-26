"""Registry for log filters contributed by plugins.

Plugins register a ``logging.Filter`` at init; the server attaches them to the
gateway logger at startup. The core carries no knowledge of what they do.
"""

import logging

_log_filters: list[logging.Filter] = []


def register_log_filter(log_filter: logging.Filter) -> None:
    _log_filters.append(log_filter)


def get_log_filters() -> list[logging.Filter]:
    return list(_log_filters)


def apply_log_filters(logger: logging.Logger) -> None:
    for log_filter in get_log_filters():
        logger.addFilter(log_filter)
