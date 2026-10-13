"""alert_rule_scopes

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
Create Date: 2026-10-13 00:00:00.000000

A rule now watches a route, a project or a credential, so PROJECT and ROUTE
become nullable and CREDENTIAL_UUID is added. WINDOW_SIZE holds the tumbling
window of a `window` rule.

Existing rows are route rules with instant aggregation. PROJECT now always holds
the project uuid: a project name is rewritten to the uuid of the live project
with that name. A name that matches no live project is left as it is and the
rule shows as stale.
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e0f1a2b3c4d5'
down_revision: Union[str, Sequence[str], None] = 'd9e0f1a2b3c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('alert_rule', 'PROJECT', nullable=True)
    op.alter_column('alert_rule', 'ROUTE', nullable=True)
    op.add_column(
        'alert_rule', sa.Column('CREDENTIAL_UUID', sa.UUID(), nullable=True)
    )
    op.add_column('alert_rule', sa.Column('WINDOW_SIZE', sa.VARCHAR(), nullable=True))

    op.execute(
        """UPDATE alert_rule SET "SCOPE" = 'route', "TIME_AGGREGATION" = 'instant'"""
    )
    op.execute(
        """
        UPDATE alert_rule AS r
        SET "PROJECT" = p."UUID"::text
        FROM project AS p
        WHERE r."PROJECT" = p."NAME" AND p."DELETED_AT" IS NULL
        """
    )


def downgrade() -> None:
    # Project and credential rules cannot exist without a project and a route.
    op.execute(
        """DELETE FROM alert_rule WHERE "PROJECT" IS NULL OR "ROUTE" IS NULL"""
    )
    op.drop_column('alert_rule', 'WINDOW_SIZE')
    op.drop_column('alert_rule', 'CREDENTIAL_UUID')
    op.alter_column('alert_rule', 'ROUTE', nullable=False)
    op.alter_column('alert_rule', 'PROJECT', nullable=False)
