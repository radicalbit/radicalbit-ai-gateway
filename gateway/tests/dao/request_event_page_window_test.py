"""Where a page lies among the hour buckets of the Requests list."""

import pytest

from radicalbit_ai_gateway.db.dao.request_event_dao import PageWindow, page_window

# Three hours, newest first, holding 5, 3 and 4 requests.
BUCKETS = [(300, 5), (200, 3), (100, 4)]


@pytest.mark.parametrize(
    ('offset', 'size', 'expected'),
    [
        # inside the newest hour
        (0, 5, PageWindow(oldest=300, newest=300, offset=0)),
        (2, 3, PageWindow(oldest=300, newest=300, offset=2)),
        # starts in one hour, ends in the next
        (3, 4, PageWindow(oldest=200, newest=300, offset=3)),
        # starts exactly where an older hour begins
        (5, 2, PageWindow(oldest=200, newest=200, offset=0)),
        # spans all three hours
        (4, 6, PageWindow(oldest=100, newest=300, offset=4)),
        # the last page is shorter than its size
        (10, 5, PageWindow(oldest=100, newest=100, offset=2)),
        (6, 50, PageWindow(oldest=100, newest=200, offset=1)),
    ],
)
def test_a_page_is_read_from_the_hours_that_hold_it(offset, size, expected):
    assert page_window(BUCKETS, offset, size) == expected


@pytest.mark.parametrize('offset', [12, 13, 500])
def test_a_page_past_the_last_row_has_no_window(offset):
    assert page_window(BUCKETS, offset, 5) is None


def test_no_request_means_no_window():
    assert page_window([], 0, 50) is None


def test_every_row_falls_in_exactly_one_page():
    total = sum(count for _, count in BUCKETS)
    # Rows numbered newest first; a window names the rows it would return.
    starts = {300: 0, 200: 5, 100: 8}
    for size in range(1, total + 2):
        seen = []
        for offset in range(0, total, size):
            window = page_window(BUCKETS, offset, size)
            first = starts[window.newest] + window.offset
            seen += range(first, min(first + size, total))
        assert seen == list(range(total))
