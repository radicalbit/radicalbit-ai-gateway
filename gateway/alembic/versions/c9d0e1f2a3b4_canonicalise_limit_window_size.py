"""canonicalise_limit_window_size

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-10-26 00:00:00.000000

"""
import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, Sequence[str], None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# parse_window and format_window of limiter/window_config.py as of this
# revision, copied so later changes there can't change what this migration does
_TIME_UNITS = {
    'second': 1,
    'seconds': 1,
    'minute': 60,
    'minutes': 60,
    'hour': 3600,
    'hours': 3600,
    'day': 86400,
    'days': 86400,
    'week': 604800,
    'weeks': 604800,
    'month': 2592000,
    'months': 2592000,
}
_CANONICAL_UNITS = (
    ('month', 2592000),
    ('week', 604800),
    ('day', 86400),
    ('hour', 3600),
    ('minute', 60),
    ('second', 1),
)
_WINDOW_PATTERN = re.compile(r'^(\d+)\s*(\w+)$')
# A window sent as a number was stored as is, e.g. '60': seconds
_SECONDS_PATTERN = re.compile(r'^\d+$')


def _canonical(window_size: str) -> str | None:
    """The window in its largest exact unit, or None when it can't be parsed."""
    window_size = window_size.strip()
    if _SECONDS_PATTERN.match(window_size):
        window_seconds = int(window_size)
    else:
        match = _WINDOW_PATTERN.match(window_size)
        if not match:
            return None
        unit = match.group(2).lower()
        if unit not in _TIME_UNITS:
            return None
        window_seconds = int(match.group(1)) * _TIME_UNITS[unit]
    if window_seconds <= 0:
        return None
    for name, seconds in _CANONICAL_UNITS:
        if window_seconds % seconds == 0:
            count = window_seconds // seconds
            return f'{count} {name}' if count == 1 else f'{count} {name}s'
    return None


def _canonicalise(table: str, signature_columns: list[str]) -> None:
    """Rewrite every WINDOW_SIZE in its canonical form.

    Rows that become the same limit already share one counter, which counts the
    window in seconds: the lowest max is the one that binds, so it survives and
    the others are deleted.
    """
    bind = op.get_bind()
    columns = ', '.join(f'"{c}"' for c in signature_columns)
    rows = bind.execute(
        sa.text(f'SELECT "UUID", {columns}, "WINDOW_SIZE", "MAX_VALUE" FROM "{table}"')
    ).all()

    groups: dict[tuple, list] = {}
    for row in rows:
        canonical = _canonical(row.WINDOW_SIZE)
        if canonical is None:
            continue
        signature = tuple(getattr(row, c) for c in signature_columns) + (canonical,)
        groups.setdefault(signature, []).append(row)

    for signature, group in groups.items():
        survivor, *duplicates = sorted(group, key=lambda row: row.MAX_VALUE)
        for duplicate in duplicates:
            bind.execute(
                sa.text(f'DELETE FROM "{table}" WHERE "UUID" = :uuid'),
                {'uuid': duplicate.UUID},
            )
        canonical = signature[-1]
        if survivor.WINDOW_SIZE != canonical:
            bind.execute(
                sa.text(f'UPDATE "{table}" SET "WINDOW_SIZE" = :window WHERE "UUID" = :uuid'),
                {'window': canonical, 'uuid': survivor.UUID},
            )


def upgrade() -> None:
    """Upgrade schema."""
    _canonicalise('key_limit', ['KEY_UUID', 'CATEGORY', 'ALGORITHM'])
    # Grouped as its unique constraint is today: (project, window)
    _canonicalise('project_budget_limit', ['PROJECT_UUID'])


def downgrade() -> None:
    """Downgrade schema."""
    # Nothing to undo: the canonical windows are valid for the previous
    # revision too, and the deleted duplicates can't be told apart any more.
