import threading
import uuid

import anyio
import pytest
from sqlalchemy import select

from tests.common import db_mock
from tests.common.db_integration import AsyncDatabaseIntegration

from radicalbit_ai_gateway.db.database import Database, filter_if, run_from_worker
from radicalbit_ai_gateway.db.tables.project_table import Project
from radicalbit_ai_gateway.utils.app_config import DBConfig


def test_the_url_uses_the_psycopg_3_driver():
    conf = DBConfig(db_host='pg', db_port=6543, db_user='u', db_pwd='p', db_name='gw')

    assert Database(conf).db_url == 'postgresql+psycopg://u:p@pg:6543/gw'


def test_the_default_config_points_at_postgres_not_sqlite():
    assert Database(DBConfig()).db_url == (
        'postgresql+psycopg://postgres:postgres@localhost:5432/radicalbit'
    )


class AsyncSessionTest(AsyncDatabaseIntegration):
    async def test_a_row_written_in_one_session_is_read_in_the_next(self):
        project = db_mock.get_sample_project(uuid=uuid.uuid4(), name='async')
        async with self.db.begin_session() as session:
            session.add(project)

        async with self.db.begin_session() as session:
            found = await session.scalar(
                select(Project).where(Project.uuid == project.uuid)
            )

        assert found.name == 'async'

    async def test_an_error_rolls_the_session_back(self):
        project = db_mock.get_sample_project(uuid=uuid.uuid4(), name='lost')
        with pytest.raises(RuntimeError):
            async with self.db.begin_session() as session:
                session.add(project)
                await session.flush()
                raise RuntimeError('boom')

        async with self.db.begin_session() as session:
            found = await session.scalar(
                select(Project).where(Project.uuid == project.uuid)
            )

        assert found is None

    async def test_attributes_stay_readable_after_commit(self):
        project = db_mock.get_sample_project(uuid=uuid.uuid4(), name='kept')
        async with self.db.begin_session() as session:
            session.add(project)

        # expire_on_commit=False: no lazy load (which async cannot do) is needed.
        assert project.name == 'kept'

    async def test_the_sync_session_reads_what_the_async_one_wrote(self):
        project = db_mock.get_sample_project(uuid=uuid.uuid4(), name='both')
        async with self.db.begin_session() as session:
            session.add(project)

        with self.db.begin_session() as session:
            found = session.scalar(select(Project).where(Project.uuid == project.uuid))

        assert found.name == 'both'


class FilterIfTest(AsyncDatabaseIntegration):
    async def asyncSetUp(self):
        for name in ('alpha', 'beta'):
            await self.insert(db_mock.get_sample_project(uuid=uuid.uuid4(), name=name))

    async def _names(self, stmt) -> list[str]:
        async with self.db.begin_session() as session:
            return sorted((await session.scalars(stmt)).all())

    async def test_a_true_condition_applies_the_clause(self):
        stmt = filter_if(select(Project.name), True, Project.name == 'alpha')

        assert await self._names(stmt) == ['alpha']

    async def test_a_false_condition_leaves_the_statement_as_is(self):
        stmt = filter_if(select(Project.name), False, Project.name == 'alpha')

        assert await self._names(stmt) == ['alpha', 'beta']

    async def test_several_clauses_all_apply(self):
        stmt = filter_if(
            select(Project.name),
            True,
            Project.name.startswith('a'),
            Project.name.endswith('z'),
        )

        assert await self._names(stmt) == []


async def test_a_sync_caller_in_a_worker_thread_runs_the_query_on_the_event_loop():
    loop_thread = threading.get_ident()

    async def query(value):
        return threading.get_ident(), value

    ran_on, value = await anyio.to_thread.run_sync(run_from_worker, query, 'v')

    assert ran_on == loop_thread
    assert value == 'v'
