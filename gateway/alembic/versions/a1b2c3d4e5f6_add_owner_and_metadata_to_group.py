"""add_owner_and_metadata_to_group

Revision ID: a1b2c3d4e5f6
Revises: 2833a41c11b2
Create Date: 2026-03-23 00:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '2833a41c11b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'group',
        sa.Column('OWNER', sa.VARCHAR(), nullable=False, server_default='gateway'),
    )
    op.add_column('group', sa.Column('METADATA', sa.TEXT(), nullable=True))
    op.drop_constraint('uq_group_NAME', 'group', type_='unique')
    op.create_unique_constraint('uq_group_NAME_OWNER', 'group', ['NAME', 'OWNER'])


def downgrade() -> None:
    op.drop_constraint('uq_group_NAME_OWNER', 'group', type_='unique')
    op.create_unique_constraint('uq_group_NAME', 'group', ['NAME'])
    op.drop_column('group', 'METADATA')
    op.drop_column('group', 'OWNER')
