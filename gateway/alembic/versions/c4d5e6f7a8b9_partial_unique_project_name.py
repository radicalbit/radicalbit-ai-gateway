"""partial_unique_project_name

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-06-12 00:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('uq_project_NAME', 'project', type_='unique')
    op.create_index(
        'uq_project_NAME',
        'project',
        ['NAME'],
        unique=True,
        postgresql_where=sa.text('"DELETED_AT" IS NULL'),
    )


def downgrade() -> None:
    op.drop_index('uq_project_NAME', table_name='project')
    op.create_unique_constraint('uq_project_NAME', 'project', ['NAME'])
