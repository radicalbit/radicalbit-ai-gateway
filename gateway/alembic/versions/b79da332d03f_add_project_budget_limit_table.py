"""add_project_budget_limit_table

Revision ID: b79da332d03f
Revises: b7c8d9e0f1a2
Create Date: 2026-09-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b79da332d03f'
down_revision: Union[str, Sequence[str], None] = 'b7c8d9e0f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'project_budget_limit',
        sa.Column('UUID', sa.UUID(), nullable=False),
        sa.Column('PROJECT_UUID', sa.UUID(), nullable=False),
        sa.Column('ALGORITHM', sa.VARCHAR(), nullable=False),
        sa.Column('WINDOW_SIZE', sa.VARCHAR(), nullable=False),
        sa.Column('MAX_VALUE', sa.NUMERIC(), nullable=False),
        sa.Column('CREATED_AT', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('UPDATED_AT', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('UUID', name=op.f('pk_project_budget_limit')),
        sa.ForeignKeyConstraint(
            ['PROJECT_UUID'],
            ['project.UUID'],
            name=op.f('fk_project_budget_limit_PROJECT_UUID_project'),
            ondelete='CASCADE',
        ),
        sa.UniqueConstraint(
            'PROJECT_UUID',
            'WINDOW_SIZE',
            name='uq_project_budget_limit_PROJECT_UUID_WINDOW_SIZE',
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('project_budget_limit')
