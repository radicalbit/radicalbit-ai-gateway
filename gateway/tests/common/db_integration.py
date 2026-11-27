import asyncio
import atexit
import functools
from typing import TypeVar
import unittest

from sqlalchemy import Constraint, delete
from testcontainers.community.postgres import PostgresContainer
from typing_extensions import override

from radicalbit_ai_gateway.db import database
from radicalbit_ai_gateway.db.database import Database
from radicalbit_ai_gateway.utils.app_config import DBConfig

T = TypeVar('T')


@functools.cache
def _postgres() -> PostgresContainer:
    """Start one Postgres for the test run: starting one takes seconds, and
    each test class creates and drops its own schema in it.
    """
    container = PostgresContainer(image='postgres:15', driver='psycopg')
    container.start()
    atexit.register(container.stop)
    return container


def _db_conf(container: PostgresContainer) -> DBConfig:
    return DBConfig(
        db_host=container.get_container_host_ip(),
        db_port=int(container.get_exposed_port(container.port)),
        db_user=container.username,
        db_pwd=container.password,
        db_name=container.dbname,
    )


async def _create_schema(db: Database) -> None:
    engine = db._async_engine
    assert engine is not None
    async with engine.begin() as conn:
        await conn.run_sync(database.BaseTable.metadata.create_all)
    await db.init_mappings()
    # The pooled connections belong to this short-lived loop: drop them.
    await db.dispose()


async def _drop_schema(db: Database) -> None:
    engine = db._async_engine
    assert engine is not None
    async with engine.begin() as conn:
        await conn.run_sync(database.BaseTable.metadata.drop_all)
    await db.dispose()


class SchemaIntegration(unittest.TestCase):
    """Create the schema in the shared Postgres when a test class starts, and
    drop it when the class ends.

    Use it as is for sync tests that reach the database through an event loop
    of their own, like a ``TestClient`` portal. Async tests use
    ``AsyncDatabaseIntegration``.
    """

    @override
    @classmethod
    def setUpClass(cls) -> None:
        cls.postgres_container = _postgres()
        cls.db_conf = _db_conf(cls.postgres_container)
        cls.db = Database(conf=cls.db_conf)
        cls.db.connect()
        asyncio.run(_create_schema(cls.db))

    @override
    @classmethod
    def tearDownClass(cls) -> None:
        asyncio.run(_drop_schema(cls.db))
        # Sanitize possible duplicated/reflected UNIQUE constraints left in metadata
        cls._sanitize_unique_constraints()
        cls.db.reset_connection()

    @classmethod
    def _sanitize_unique_constraints(cls) -> None:
        """Remove duplicated UNIQUE constraints that may have been added by reflection.
        This avoids re-emitting both UNIQUE and UNIQUE NULLS DISTINCT on the same columns.

        `table.constraints` is a set, so iteration order is not deterministic.
        Grouping by (name, cols) before deciding which copy to keep avoids a
        prior bug where, depending on iteration order, both the declared and
        the reflected copy of a constraint could independently match removal
        criteria and both end up removed, dropping the constraint entirely.
        """
        for table in list(database.BaseTable.metadata.tables.values()):
            groups: dict[tuple[str, tuple[str, ...]], list[Constraint]] = {}
            for constraint in table.constraints:
                if type(constraint).__name__ != 'UniqueConstraint':
                    continue
                name = constraint.name or ''
                cols = tuple(col.name for col in constraint.columns)
                groups.setdefault((name, cols), []).append(constraint)

            def _has_nulls_kwarg(constraint) -> bool:
                dialect_kwargs = getattr(constraint, 'dialect_kwargs', {}) or {}
                return any('nulls' in k for k in dialect_kwargs)

            to_remove = []
            for constraints in groups.values():
                # Prefer to keep a copy with no dialect-added NULLS variant
                # (the declared one); fall back to an arbitrary copy so a
                # constraint is never dropped entirely.
                survivor = next(
                    (c for c in constraints if not _has_nulls_kwarg(c)),
                    constraints[0],
                )
                to_remove.extend(c for c in constraints if c is not survivor)

            for c in to_remove:
                table.constraints.remove(c)

            # Remove duplicate indexes (by name) that reflection may have
            # re-added alongside model-declared ones (e.g. partial unique
            # indexes), which would make a later create_all emit them twice.
            seen_idx: set[str] = set()
            for index in list(table.indexes):
                if index.name in seen_idx:
                    table.indexes.discard(index)
                else:
                    seen_idx.add(index.name)


async def delete_all_rows(db: Database) -> None:
    async with db.begin_session() as session:
        for table in reversed(database.BaseTable.metadata.sorted_tables):
            await session.execute(delete(table))


async def insert_row(db: Database, row: T) -> T:
    async with db.begin_session() as session:
        session.add(row)
        await session.flush()
        return row


class AsyncDatabaseIntegration(SchemaIntegration, unittest.IsolatedAsyncioTestCase):
    """Async base: tests are ``async def`` and use
    ``async with self.db.begin_session()``. Every row is deleted after each test.
    """

    @override
    async def asyncTearDown(self):
        await delete_all_rows(self.db)
        # Each test runs on its own event loop. A pooled async connection is
        # bound to the loop that opened it, so close them all here.
        await self.db.dispose()

    async def insert(self, row: T) -> T:
        return await insert_row(self.db, row)
