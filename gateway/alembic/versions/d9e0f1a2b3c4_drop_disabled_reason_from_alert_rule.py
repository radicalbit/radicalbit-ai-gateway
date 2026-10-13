"""drop_disabled_reason_from_alert_rule

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-10-12 00:00:00.000000

Staleness is computed on read, so the stored reason is gone. Rules that were
auto-disabled keep ENABLED = false.
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd9e0f1a2b3c4'
down_revision: Union[str, Sequence[str], None] = 'c8d9e0f1a2b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('alert_rule', 'DISABLED_REASON')


def downgrade() -> None:
    op.add_column('alert_rule', sa.Column('DISABLED_REASON', sa.TEXT(), nullable=True))
