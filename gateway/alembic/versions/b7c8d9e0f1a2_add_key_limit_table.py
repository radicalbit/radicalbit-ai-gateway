"""add_key_limit_table

Revision ID: b7c8d9e0f1a2
Revises: af9453aaa568
Create Date: 2026-09-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, Sequence[str], None] = 'af9453aaa568'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'key_limit',
        sa.Column('UUID', sa.UUID(), nullable=False),
        sa.Column('KEY_UUID', sa.UUID(), nullable=False),
        sa.Column('CATEGORY', sa.VARCHAR(), nullable=False),
        sa.Column('ALGORITHM', sa.VARCHAR(), nullable=False),
        sa.Column('WINDOW_SIZE', sa.VARCHAR(), nullable=False),
        sa.Column('MAX_VALUE', sa.NUMERIC(), nullable=False),
        sa.Column('CREATED_AT', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('UPDATED_AT', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('UUID', name=op.f('pk_key_limit')),
        sa.ForeignKeyConstraint(
            ['KEY_UUID'],
            ['key.UUID'],
            name=op.f('fk_key_limit_KEY_UUID_key'),
            ondelete='CASCADE',
        ),
        sa.UniqueConstraint(
            'KEY_UUID',
            'CATEGORY',
            'ALGORITHM',
            'WINDOW_SIZE',
            name='uq_key_limit_KEY_UUID_CATEGORY_ALGORITHM_WINDOW_SIZE',
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('key_limit')
