"""project_budget_limit_unique_per_algorithm

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-10-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd0e1f2a3b4c5'
down_revision: Union[str, Sequence[str], None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(
        'uq_project_budget_limit_PROJECT_UUID_WINDOW_SIZE',
        'project_budget_limit',
        type_='unique',
    )
    op.create_unique_constraint(
        'uq_project_budget_limit_PROJECT_UUID_ALGORITHM_WINDOW_SIZE',
        'project_budget_limit',
        ['PROJECT_UUID', 'ALGORITHM', 'WINDOW_SIZE'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Fails if a project has two budgets on the same window with different
    # algorithms: delete one of them first
    op.drop_constraint(
        'uq_project_budget_limit_PROJECT_UUID_ALGORITHM_WINDOW_SIZE',
        'project_budget_limit',
        type_='unique',
    )
    op.create_unique_constraint(
        'uq_project_budget_limit_PROJECT_UUID_WINDOW_SIZE',
        'project_budget_limit',
        ['PROJECT_UUID', 'WINDOW_SIZE'],
    )
