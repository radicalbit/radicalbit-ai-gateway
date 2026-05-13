"""add_first_served_at_to_project

Revision ID: f1a2b3c4d5e6
Revises: e1f2a3b4c5d6
Create Date: 2026-05-07 00:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'project',
        sa.Column('FIRST_SERVED_AT', sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.execute(
        'UPDATE project SET "FIRST_SERVED_AT" = "UPDATED_AT" WHERE "CONFIG_FILE" IS NOT NULL'
    )


def downgrade() -> None:
    op.drop_column('project', 'FIRST_SERVED_AT')
