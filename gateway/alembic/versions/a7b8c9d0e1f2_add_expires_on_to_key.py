"""add_expires_on_to_key

Revision ID: a7b8c9d0e1f2
Revises: e0f1a2b3c4d5
Create Date: 2026-10-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'e0f1a2b3c4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nullable on purpose: existing credentials get no expiry date (Never)
    op.add_column('key', sa.Column('EXPIRES_ON', sa.DATE(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('key', 'EXPIRES_ON')
