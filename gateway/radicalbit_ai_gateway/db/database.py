from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
import logging
from typing import TypeVar

import anyio
from sqlalchemy import ColumnElement, Delete, MetaData, Select, Update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.declarative import DeferredReflection
from sqlalchemy.orm import declarative_base

from radicalbit_ai_gateway.utils.app_config import DBConfig, get_app_config

logger = logging.getLogger(get_app_config().log_config.logger_name)


Stmt = TypeVar('Stmt', Select, Update, Delete)


def filter_if(stmt: Stmt, condition: bool, *clauses: ColumnElement[bool]) -> Stmt:
    """Add the clauses to the statement's WHERE only when the condition holds."""
    return stmt.where(*clauses) if condition else stmt


R = TypeVar('R')


def run_from_worker(async_fn: Callable[..., Awaitable[R]], *args) -> R:
    """Run an async DB call on the event loop from sync code in a worker thread,
    and wait for its result.

    For sync routes that stay sync (their ClickHouse work runs in FastAPI's
    thread pool) but read a Postgres DAO: the pooled connections belong to the
    event loop, so the query must run there.
    Raises RuntimeError when called from the event loop itself.
    """
    return anyio.from_thread.run(async_fn, *args)


_POOL = {'pool_pre_ping': True, 'pool_size': 20, 'max_overflow': 40}


class Reflected(DeferredReflection):
    __abstract__ = True


# https://github.com/sqlalchemy/alembic/discussions/1532
# https://alembic.sqlalchemy.org/en/latest/naming.html
naming_convention = {
    'ix': 'ix_%(column_0_label)s',
    'uq': 'uq_%(table_name)s_%(column_0_name)s',
    'ck': 'ck_%(table_name)s_%(constraint_name)s',
    'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s',
    'pk': 'pk_%(table_name)s',
}

# https://github.com/sqlalchemy/alembic/discussions/1351
# If the schema is the default, Alembic needs None otherwise migrations are messed up
fixed_schema = (
    None
    if get_app_config().db_config.db_schema == 'public'
    else get_app_config().db_config.db_schema
)
BaseTable = declarative_base(
    metadata=MetaData(schema=fixed_schema, naming_convention=naming_convention)
)


class Database:
    def __init__(self, conf: DBConfig):
        self._conf = conf
        self._db_url = self._build_db_url()
        self._async_engine = None
        self._AsyncSessionFactory = None
        self._connected = False

    def _build_db_url(self) -> str:
        c = self._conf
        return f'postgresql+psycopg://{c.db_user}:{c.db_pwd}@{c.db_host}:{c.db_port}/{c.db_name}'

    def connect(self):
        """Build the engine. It opens no connection yet."""
        logger.info('Trying to connect to Postgres DB')
        if not self._connected:
            logger.info('Connecting to Postgres DB')
            self._async_engine = create_async_engine(self._db_url, **_POOL)
            self._AsyncSessionFactory = async_sessionmaker(
                bind=self._async_engine, expire_on_commit=False
            )
            self._connected = True
        else:
            logger.warning('Not connecting. Connection with the DB already established')

    async def dispose(self):
        """Close the pooled connections."""
        if self._async_engine is not None:
            await self._async_engine.dispose()

    def reset_connection(self):
        logger.info('Resetting DB connection')
        self._async_engine = None
        self._AsyncSessionFactory = None
        self._connected = False

    async def init_mappings(self):
        logger.info('Initiating DB orm mappings')
        async with self._async_engine.connect() as conn:
            await conn.run_sync(Reflected.prepare, views=True)

    def begin_session(self) -> AbstractAsyncContextManager[AsyncSession]:
        """One transaction, opened with ``async with``: it yields an
        ``AsyncSession``, commits on success and rolls back on error.
        """
        return self._AsyncSessionFactory.begin()

    @property
    def db_url(self):
        return self._db_url
