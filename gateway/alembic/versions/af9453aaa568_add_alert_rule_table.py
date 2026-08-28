"""add_alert_rule_table

Revision ID: af9453aaa568
Revises: b4c5d6e7f8a9
Create Date: 2026-08-07 14:10:14.940030

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'af9453aaa568'
down_revision: Union[str, Sequence[str], None] = 'b4c5d6e7f8a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'alert_rule',
        sa.Column('UUID', sa.UUID(), nullable=False),
        sa.Column('NAME', sa.VARCHAR(), nullable=False),
        sa.Column('DESCRIPTION', sa.TEXT(), nullable=True),
        sa.Column('PROJECT', sa.VARCHAR(), nullable=False),
        sa.Column('ROUTE', sa.VARCHAR(), nullable=False),
        sa.Column('SCOPE', sa.VARCHAR(), nullable=False, server_default='route'),
        sa.Column('EVENT', sa.VARCHAR(), nullable=False),
        sa.Column(
            'TIME_AGGREGATION',
            sa.VARCHAR(),
            nullable=False,
            server_default='instant',
        ),
        sa.Column(
            'CHANNEL', sa.VARCHAR(), nullable=False, server_default='email'
        ),
        sa.Column('RECIPIENTS', sa.TEXT(), nullable=False),
        sa.Column(
            'ENABLED', sa.BOOLEAN(), nullable=False, server_default=sa.text('false')
        ),
        sa.Column('DISABLED_REASON', sa.TEXT(), nullable=True),
        sa.Column(
            'DELETED', sa.BOOLEAN(), nullable=False, server_default=sa.text('false')
        ),
        sa.Column('CREATED_AT', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('UPDATED_AT', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('UUID', name=op.f('pk_alert_rule')),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('alert_rule')
