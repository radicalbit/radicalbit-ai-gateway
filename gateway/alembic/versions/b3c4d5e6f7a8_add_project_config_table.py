"""add_project_config_table

Splits project configurations into a dedicated ``project_config`` table
(two permanent slots A/B per project, at most one SERVED) and migrates the
legacy ``CONFIG_FILE`` / ``DRAFT_CONFIG_FILE`` / ``CONFIG_STATUS`` columns of
``project`` into it. See AG-778.

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-06-10 00:00:00.000000

"""

from collections.abc import Sequence
import datetime
from typing import Union
import uuid

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

from radicalbit_ai_gateway.utils.yaml_utils import get_default_config_template

# revision identifiers, used by Alembic.
revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UTC = getattr(datetime, 'UTC', datetime.timezone.utc)

_INSERT_CONFIG = sa.text(
    'INSERT INTO project_config '
    '("UUID", "PROJECT_UUID", "SLOT", "CONFIG_FILE", "CONFIG_STATUS", '
    '"CREATED_AT", "UPDATED_AT", "DELETED_AT") '
    'VALUES (:uuid, :project_uuid, CAST(:slot AS project_config_slot), '
    ':config_file, CAST(:status AS project_config_status), '
    ':created_at, :updated_at, :deleted_at)'
)


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Enums: create the new slot enum explicitly; the config_status enum
    #    already exists and is reused. Both are passed to create_table with
    #    create_type=False so it does not (re)emit CREATE TYPE.
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

    # 2. project_config table.
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
    # At most one SERVED config per project.
    op.create_index(
        'uq_project_config_served',
        'project_config',
        ['PROJECT_UUID'],
        unique=True,
        postgresql_where=sa.text('"CONFIG_STATUS" = \'SERVED\''),
    )

    # 3. Reference to the served config on the project row.
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

    # 4. Data migration: every project ends up with exactly 2 slots (A, B).
    template = get_default_config_template()
    projects = bind.execute(
        sa.text(
            'SELECT "UUID", "CONFIG_FILE", "DRAFT_CONFIG_FILE", "CONFIG_STATUS", '
            '"UPDATED_AT", "DELETED_AT" FROM project'
        )
    ).fetchall()

    for row in projects:
        project_uuid = row[0]
        config_file = row[1]
        draft_config_file = row[2]
        config_status = row[3]
        updated_at = row[4]
        deleted_at = row[5]

        has_served = config_file is not None

        # Slot A: the served config, or an empty template draft.
        slot_a_uuid = uuid.uuid4()
        bind.execute(
            _INSERT_CONFIG,
            {
                'uuid': slot_a_uuid,
                'project_uuid': project_uuid,
                'slot': 'A',
                'config_file': config_file if has_served else template,
                'status': 'SERVED' if has_served else 'DRAFT',
                'created_at': updated_at,
                'updated_at': updated_at,
                'deleted_at': deleted_at,
            },
        )

        # Slot B: the editable draft, or an empty template draft.
        if draft_config_file is not None:
            slot_b_file = draft_config_file
            slot_b_status = (
                config_status
                if config_status in ('DRAFT', 'READY_TO_SERVE')
                else 'DRAFT'
            )
        else:
            slot_b_file = template
            slot_b_status = 'DRAFT'

        bind.execute(
            _INSERT_CONFIG,
            {
                'uuid': uuid.uuid4(),
                'project_uuid': project_uuid,
                'slot': 'B',
                'config_file': slot_b_file,
                'status': slot_b_status,
                'created_at': updated_at,
                'updated_at': updated_at,
                'deleted_at': deleted_at,
            },
        )

        if has_served:
            bind.execute(
                sa.text(
                    'UPDATE project SET "SERVED_CONFIG_UUID" = :served '
                    'WHERE "UUID" = :project_uuid'
                ),
                {'served': slot_a_uuid, 'project_uuid': project_uuid},
            )

    # 5. Drop legacy columns (keep FIRST_SERVED_AT).
    op.drop_column('project', 'CONFIG_STATUS')
    op.drop_column('project', 'DRAFT_CONFIG_FILE')
    op.drop_column('project', 'CONFIG_FILE')


def downgrade() -> None:
    bind = op.get_bind()

    # 1. Re-add legacy columns.
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

    # 2. Best-effort reconstruction of the single-row model.
    #    config_file <- SERVED slot; draft_config_file <- the non-served slot
    #    (prefer B). config_status is SERVED whenever a served slot exists,
    #    else the non-served slot's status. The two-slot split is lossy, so a
    #    parallel draft's pending status is not preserved on downgrade.
    projects = bind.execute(sa.text('SELECT "UUID" FROM project')).fetchall()
    for (project_uuid,) in projects:
        configs = bind.execute(
            sa.text(
                'SELECT "SLOT", "CONFIG_FILE", "CONFIG_STATUS" FROM project_config '
                'WHERE "PROJECT_UUID" = :project_uuid'
            ),
            {'project_uuid': project_uuid},
        ).fetchall()

        served = next((c for c in configs if c[2] == 'SERVED'), None)
        non_served = [c for c in configs if c[2] != 'SERVED']
        # Prefer slot B as the draft carrier, else the first non-served slot.
        draft = next(
            (c for c in non_served if c[0] == 'B'),
            non_served[0] if non_served else None,
        )

        bind.execute(
            sa.text(
                'UPDATE project SET "CONFIG_FILE" = :config_file, '
                '"DRAFT_CONFIG_FILE" = :draft_file, '
                '"CONFIG_STATUS" = CAST(:status AS project_config_status) '
                'WHERE "UUID" = :project_uuid'
            ),
            {
                'config_file': served[1] if served else None,
                'draft_file': draft[1] if draft else None,
                'status': 'SERVED'
                if served
                else (draft[2] if draft else 'DRAFT'),
                'project_uuid': project_uuid,
            },
        )

    # 3. Drop the served reference, then the table, then the slot enum.
    op.drop_constraint(
        'fk_project_SERVED_CONFIG_UUID_project_config', 'project', type_='foreignkey'
    )
    op.drop_column('project', 'SERVED_CONFIG_UUID')
    op.drop_index('uq_project_config_served', table_name='project_config')
    op.drop_table('project_config')
    sa.Enum(name='project_config_slot').drop(bind, checkfirst=True)
