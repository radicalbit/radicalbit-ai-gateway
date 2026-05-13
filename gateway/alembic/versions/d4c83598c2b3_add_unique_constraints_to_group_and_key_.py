"""add_unique_constraints_to_group_and_key_names

Revision ID: d4c83598c2b3
Revises: d4a1dded792c
Create Date: 2025-11-13 11:34:07.248221

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4c83598c2b3'
down_revision: Union[str, Sequence[str], None] = 'd4a1dded792c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add unique constraint to group.NAME
    op.create_unique_constraint(
        op.f('uq_group_NAME'),
        'group',
        ['NAME']
    )
    # Add unique constraint to key.NAME
    op.create_unique_constraint(
        op.f('uq_key_NAME'),
        'key',
        ['NAME']
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Remove unique constraint from key.NAME
    op.drop_constraint(
        op.f('uq_key_NAME'),
        'key',
        type_='unique'
    )
    # Remove unique constraint from group.NAME
    op.drop_constraint(
        op.f('uq_group_NAME'),
        'group',
        type_='unique'
    )
