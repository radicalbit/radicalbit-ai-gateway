"""add_rotation_to_key

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-10-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nullable on purpose: existing credentials have never been rotated
    op.add_column('key', sa.Column('PREVIOUS_HASHED_KEY', sa.VARCHAR(length=128), nullable=True))
    op.add_column('key', sa.Column('GRACE_ENDS_AT', sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column('key', sa.Column('LAST_ROTATED_AT', sa.TIMESTAMP(timezone=True), nullable=True))
    op.create_index('ix_key_PREVIOUS_HASHED_KEY', 'key', ['PREVIOUS_HASHED_KEY'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_key_PREVIOUS_HASHED_KEY', table_name='key')
    op.drop_column('key', 'LAST_ROTATED_AT')
    op.drop_column('key', 'GRACE_ENDS_AT')
    op.drop_column('key', 'PREVIOUS_HASHED_KEY')
