"""rename_key_id_to_name

Revision ID: 6498c03a5fcb
Revises: 52b10f350046
Create Date: 2025-08-28 13:25:28.140907

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6498c03a5fcb'
down_revision: Union[str, Sequence[str], None] = '52b10f350046'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Rename ID column to NAME to preserve data
    op.alter_column('key', 'ID', new_column_name='NAME')


def downgrade() -> None:
    """Downgrade schema."""
    # Rename NAME column back to ID
    op.alter_column('key', 'NAME', new_column_name='ID')
