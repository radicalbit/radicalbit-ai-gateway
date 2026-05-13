"""refactor key to foreign key

Revision ID: 2833a41c11b2
Revises: d4c83598c2b3
Create Date: 2025-11-21 16:38:15.293630

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '2833a41c11b2'
down_revision: Union[str, Sequence[str], None] = 'd4c83598c2b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add GROUP_UUID column to key table
    op.add_column('key', sa.Column('GROUP_UUID', sa.UUID(), nullable=True))

    # Create foreign key constraint
    op.create_foreign_key(
        op.f('fk_key_GROUP_UUID_group'),
        'key', 'group',
        ['GROUP_UUID'], ['UUID'],
        ondelete='CASCADE'
    )
    # Drop the old association table
    op.drop_table('group_keys')


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        'group_keys',
        sa.Column('GROUP_UUID', sa.UUID(), nullable=False),
        sa.Column('USER_KEY_UUID', sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(['GROUP_UUID'], ['group.UUID'], name=op.f('fk_group_keys_GROUP_UUID_group'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['USER_KEY_UUID'], ['user_key.UUID'], name=op.f('fk_group_keys_USER_KEY_UUID_user_key'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('GROUP_UUID', 'USER_KEY_UUID', name=op.f('pk_group_keys'))
    )

    # 3. Drop the Foreign Key and the Column from the key table.
    op.drop_constraint(op.f('fk_key_GROUP_UUID_group'), 'key', type_='foreignkey')
    op.drop_column('key', 'GROUP_UUID')
