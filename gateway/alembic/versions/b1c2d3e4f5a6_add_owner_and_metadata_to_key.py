"""add_owner_and_metadata_to_key

Revision ID: b1c2d3e4f5a6
Revises: a1b2c3d4e5f6
Create Date: 2026-03-23 00:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'key',
        sa.Column('OWNER', sa.VARCHAR(), nullable=False, server_default='gateway'),
    )
    op.add_column('key', sa.Column('METADATA', sa.TEXT(), nullable=True))
    op.drop_constraint('uq_key_NAME', 'key', type_='unique')
    op.create_unique_constraint('uq_key_NAME_OWNER', 'key', ['NAME', 'OWNER'])


def downgrade() -> None:
    op.drop_constraint('uq_key_NAME_OWNER', 'key', type_='unique')
    op.create_unique_constraint('uq_key_NAME', 'key', ['NAME'])
    op.drop_column('key', 'METADATA')
    op.drop_column('key', 'OWNER')
