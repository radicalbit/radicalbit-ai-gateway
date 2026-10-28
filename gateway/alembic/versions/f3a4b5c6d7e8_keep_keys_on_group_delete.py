"""keep_keys_on_group_delete

Deleting a group leaves its credentials, without a group.

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-10-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f3a4b5c6d7e8'
down_revision: Union[str, Sequence[str], None] = 'e2f3a4b5c6d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _recreate_key_group_fk(ondelete: str) -> None:
    op.drop_constraint(op.f('fk_key_GROUP_UUID_group'), 'key', type_='foreignkey')
    op.create_foreign_key(
        op.f('fk_key_GROUP_UUID_group'),
        'key',
        'group',
        ['GROUP_UUID'],
        ['UUID'],
        ondelete=ondelete,
    )


def upgrade() -> None:
    _recreate_key_group_fk('SET NULL')


def downgrade() -> None:
    _recreate_key_group_fk('CASCADE')
