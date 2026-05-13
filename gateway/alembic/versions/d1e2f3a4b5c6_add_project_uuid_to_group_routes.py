"""add_project_uuid_to_group_routes

Revision ID: d1e2f3a4b5c6
Revises: c1d2e3f4a5b6
Create Date: 2026-04-20 00:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add PROJECT_UUID as nullable first (safe for tables with existing rows)
    op.add_column(
        'group_routes',
        sa.Column('PROJECT_UUID', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'fk_group_routes_PROJECT_UUID_project',
        'group_routes',
        'project',
        ['PROJECT_UUID'],
        ['UUID'],
        ondelete='CASCADE',
    )
    # Remove rows without a project_uuid (legacy global routes, now unsupported)
    op.execute('DELETE FROM group_routes WHERE "PROJECT_UUID" IS NULL')
    # Make PROJECT_UUID NOT NULL
    op.alter_column('group_routes', 'PROJECT_UUID', nullable=False)
    # Replace PK (GROUP_UUID, ROUTE_NAME) with (GROUP_UUID, PROJECT_UUID, ROUTE_NAME)
    op.drop_constraint('pk_group_routes', 'group_routes', type_='primary')
    op.create_primary_key(
        'pk_group_routes',
        'group_routes',
        ['GROUP_UUID', 'PROJECT_UUID', 'ROUTE_NAME'],
    )


def downgrade() -> None:
    op.drop_constraint('pk_group_routes', 'group_routes', type_='primary')
    op.create_primary_key(
        'pk_group_routes', 'group_routes', ['GROUP_UUID', 'ROUTE_NAME']
    )
    op.alter_column('group_routes', 'PROJECT_UUID', nullable=True)
    op.drop_constraint(
        'fk_group_routes_PROJECT_UUID_project',
        'group_routes',
        type_='foreignkey',
    )
    op.drop_column('group_routes', 'PROJECT_UUID')
