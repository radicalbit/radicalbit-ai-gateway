"""add_group_limit_table

Revision ID: c8d9e0f1a2b3
Revises: b79da332d03f
Create Date: 2026-09-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c8d9e0f1a2b3'
down_revision: Union[str, Sequence[str], None] = 'b79da332d03f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
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


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        op.f('fk_key_limit_GROUP_LIMIT_UUID_group_limit'),
        'key_limit',
        type_='foreignkey',
    )
    op.drop_column('key_limit', 'GROUP_LIMIT_UUID')
    op.drop_table('group_limit')
