"""add pk to group_keys

Revision ID: d4a1dded792c
Revises: 6498c03a5fcb
Create Date: 2025-09-09 11:34:22.306140

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4a1dded792c'
down_revision: Union[str, Sequence[str], None] = '6498c03a5fcb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Adds a primary key constraint to the 'id' column of 'group_keys'
    op.create_primary_key(
        op.f('pk_group_keys'),
        'group_keys',
        ['GROUP_UUID', 'KEY_UUID']
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Removes the primary key constraint from 'group_keys'
    op.drop_constraint(
        op.f('pk_group_keys'),
        'group_keys',
        type_='primary'
    )
