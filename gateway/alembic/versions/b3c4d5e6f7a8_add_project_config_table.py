"""add_project_config_table

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-06-10 00:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    slot_enum = postgresql.ENUM(
        'A', 'B', name='project_config_slot', create_type=False
    )
    slot_enum.create(bind, checkfirst=True)
    status_enum = postgresql.ENUM(
        'DRAFT',
        'READY_TO_SERVE',
        'SERVED',
        name='project_config_status',
        create_type=False,
    )

    op.create_table(
        'project_config',
        sa.Column('UUID', sa.UUID(), nullable=False),
        sa.Column('PROJECT_UUID', sa.UUID(), nullable=False),
        sa.Column('SLOT', slot_enum, nullable=False),
        sa.Column('CONFIG_FILE', sa.TEXT(), nullable=True),
        sa.Column(
            'CONFIG_STATUS',
            status_enum,
            nullable=False,
            server_default='DRAFT',
        ),
        sa.Column('CREATED_AT', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('UPDATED_AT', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('DELETED_AT', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('UUID', name='pk_project_config'),
        sa.ForeignKeyConstraint(
            ['PROJECT_UUID'],
            ['project.UUID'],
            name='fk_project_config_PROJECT_UUID_project',
            ondelete='CASCADE',
        ),
        sa.UniqueConstraint(
            'PROJECT_UUID', 'SLOT', name='uq_project_config_PROJECT_UUID_SLOT'
        ),
    )
    op.create_index(
        'uq_project_config_served',
        'project_config',
        ['PROJECT_UUID'],
        unique=True,
        postgresql_where=sa.text('"CONFIG_STATUS" = \'SERVED\''),
    )

    op.add_column(
        'project',
        sa.Column('SERVED_CONFIG_UUID', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'fk_project_SERVED_CONFIG_UUID_project_config',
        'project',
        'project_config',
        ['SERVED_CONFIG_UUID'],
        ['UUID'],
        ondelete='SET NULL',
    )

    op.drop_column('project', 'CONFIG_STATUS')
    op.drop_column('project', 'DRAFT_CONFIG_FILE')
    op.drop_column('project', 'CONFIG_FILE')


def downgrade() -> None:
    bind = op.get_bind()

    op.add_column('project', sa.Column('CONFIG_FILE', sa.TEXT(), nullable=True))
    op.add_column(
        'project', sa.Column('DRAFT_CONFIG_FILE', sa.TEXT(), nullable=True)
    )
    op.add_column(
        'project',
        sa.Column(
            'CONFIG_STATUS',
            postgresql.ENUM(
                'DRAFT',
                'READY_TO_SERVE',
                'SERVED',
                name='project_config_status',
                create_type=False,
            ),
            nullable=False,
            server_default='DRAFT',
        ),
    )

    op.drop_constraint(
        'fk_project_SERVED_CONFIG_UUID_project_config', 'project', type_='foreignkey'
    )
    op.drop_column('project', 'SERVED_CONFIG_UUID')
    op.drop_index('uq_project_config_served', table_name='project_config')
    op.drop_table('project_config')
    sa.Enum(name='project_config_slot').drop(bind, checkfirst=True)
