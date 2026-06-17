"""make_project_config_updated_at_nullable

Revision ID: b4c5d6e7f8a9
Revises: c4d5e6f7a8b9
Create Date: 2026-06-15 00:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b4c5d6e7f8a9'
down_revision: Union[str, None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'project_config',
        'UPDATED_AT',
        existing_type=sa.TIMESTAMP(timezone=True),
        nullable=True,
    )
    op.execute(
        'UPDATE project_config SET "UPDATED_AT" = NULL '
        'WHERE "UPDATED_AT" = "CREATED_AT"'
    )


def downgrade() -> None:
    op.execute(
        'UPDATE project_config SET "UPDATED_AT" = "CREATED_AT" '
        'WHERE "UPDATED_AT" IS NULL'
    )
    op.alter_column(
        'project_config',
        'UPDATED_AT',
        existing_type=sa.TIMESTAMP(timezone=True),
        nullable=False,
    )
