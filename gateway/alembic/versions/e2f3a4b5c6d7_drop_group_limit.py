"""drop_group_limit

A group owns no limits (ADR 0009): the copies made from group limits stay as
plain credential limits, then the link and the group_limit table go away.

Revision ID: e2f3a4b5c6d7
Revises: d0e1f2a3b4c5
Create Date: 2026-10-27 00:00:00.000000

"""
import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e2f3a4b5c6d7'
down_revision: Union[str, Sequence[str], None] = 'd0e1f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# _canonical and _canonicalise of c9d0e1f2a3b4, copied so later changes there
# can't change what this migration does
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
    op.execute('UPDATE "key_limit" SET "GROUP_LIMIT_UUID" = NULL')
    op.drop_constraint(
        op.f('fk_key_limit_GROUP_LIMIT_UUID_group_limit'),
        'key_limit',
        type_='foreignkey',
    )
    op.drop_column('key_limit', 'GROUP_LIMIT_UUID')
    op.drop_table('group_limit')
    # Group limits were copied with their window as sent, also after
    # c9d0e1f2a3b4: canonicalise those copies like every other credential limit
    _canonicalise('key_limit', ['KEY_UUID', 'CATEGORY', 'ALGORITHM'])


def downgrade() -> None:
    """Downgrade schema."""
    # The group limits and their link to the copies are gone for good: this
    # only restores the empty table and column
    op.create_table(
        'group_limit',
        sa.Column('UUID', sa.UUID(), nullable=False),
        sa.Column('GROUP_UUID', sa.UUID(), nullable=False),
        sa.Column('CATEGORY', sa.VARCHAR(), nullable=False),
        sa.Column('ALGORITHM', sa.VARCHAR(), nullable=False),
        sa.Column('WINDOW_SIZE', sa.VARCHAR(), nullable=False),
        sa.Column('MAX_VALUE', sa.NUMERIC(), nullable=False),
        sa.Column('CREATED_AT', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('UPDATED_AT', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('UUID', name=op.f('pk_group_limit')),
        sa.ForeignKeyConstraint(
            ['GROUP_UUID'],
            ['group.UUID'],
            name=op.f('fk_group_limit_GROUP_UUID_group'),
            ondelete='CASCADE',
        ),
        sa.UniqueConstraint(
            'GROUP_UUID',
            'CATEGORY',
            'ALGORITHM',
            'WINDOW_SIZE',
            name='uq_group_limit_GROUP_UUID_CATEGORY_ALGORITHM_WINDOW_SIZE',
        ),
    )
    op.add_column('key_limit', sa.Column('GROUP_LIMIT_UUID', sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f('fk_key_limit_GROUP_LIMIT_UUID_group_limit'),
        'key_limit',
        'group_limit',
        ['GROUP_LIMIT_UUID'],
        ['UUID'],
        ondelete='CASCADE',
    )
