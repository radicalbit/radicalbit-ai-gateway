"""create_project_table

Revision ID: c1d2e3f4a5b6
Revises: b1c2d3e4f5a6
Create Date: 2026-04-13 00:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'project',
        sa.Column('UUID', sa.UUID(), nullable=False),
        sa.Column('NAME', sa.VARCHAR(), nullable=False),
        sa.Column('DESCRIPTION', sa.TEXT(), nullable=True),
        sa.Column('CONFIG_FILE', sa.TEXT(), nullable=True),
        sa.Column('DRAFT_CONFIG_FILE', sa.TEXT(), nullable=True),
        sa.Column('CREATED_AT', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('UPDATED_AT', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('UUID', name='pk_project'),
        sa.UniqueConstraint('NAME', name='uq_project_NAME'),
    )


def downgrade() -> None:
    op.drop_table('project')
