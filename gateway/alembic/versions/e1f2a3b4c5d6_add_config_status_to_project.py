"""add_config_status_to_project

Revision ID: e1f2a3b4c5d6
Revises: d1e2f3a4b5c6
Create Date: 2026-04-28 00:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    config_status_enum = sa.Enum(
        'DRAFT', 'READY_TO_SERVE', 'SERVED',
        name='project_config_status',
        create_type=True,
    )
    config_status_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'project',
        sa.Column(
            'CONFIG_STATUS',
            config_status_enum,
            nullable=False,
            server_default='DRAFT',
        ),
    )


def downgrade() -> None:
    op.drop_column('project', 'CONFIG_STATUS')
    config_status_enum = sa.Enum(name='project_config_status')
    config_status_enum.drop(op.get_bind(), checkfirst=True)
