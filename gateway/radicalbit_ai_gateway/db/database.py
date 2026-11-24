import logging
from typing import TypeVar

from sqlalchemy import ColumnElement, Delete, MetaData, Select, Update, create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.declarative import DeferredReflection
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from radicalbit_ai_gateway.db.custom_query import CustomQuery
from radicalbit_ai_gateway.utils.app_config import DBConfig, get_app_config

logger = logging.getLogger(get_app_config().log_config.logger_name)


Stmt = TypeVar('Stmt', Select, Update, Delete)


def filter_if(stmt: Stmt, condition: bool, *clauses: ColumnElement[bool]) -> Stmt:
    """Add the clauses to the statement's WHERE only when the condition holds.
    The 2.0 ``select()`` twin of ``CustomQuery.filter_if``.
    """
    return stmt.where(*clauses) if condition else stmt


# Same pool for the async and the sync engine.
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


class SessionScope:
    """One transaction: commit on success, rollback on error.

    Open it with ``async with`` for an ``AsyncSession`` or with ``with`` for a
    sync ``Session``. The sync way stays only until Async 05 removes the sync
    engine.
    """

    def __init__(self, database: 'Database'):
        self._database = database
        self._scope = None

    def __enter__(self) -> Session:
        """Open a sync transaction."""
        self._scope = self._database._SessionFactory.begin()
        return self._scope.__enter__()

    def __exit__(self, *exc_info):
        """Commit, or roll back on error."""
        return self._scope.__exit__(*exc_info)

    async def __aenter__(self) -> AsyncSession:
        """Open an async transaction."""
        self._scope = self._database._AsyncSessionFactory.begin()
        return await self._scope.__aenter__()

    async def __aexit__(self, *exc_info):
        """Commit, or roll back on error."""
        return await self._scope.__aexit__(*exc_info)


class Database:
    def __init__(self, conf: DBConfig):
        self._conf = conf
        self._db_url = self._build_db_url()
        self._engine = None
        self._SessionFactory = None
        self._async_engine = None
        self._AsyncSessionFactory = None
        self._connected = False

    def _build_db_url(self) -> str:
        c = self._conf
        return f'postgresql+psycopg://{c.db_user}:{c.db_pwd}@{c.db_host}:{c.db_port}/{c.db_name}'

    def connect(self):
        """Build the async and the sync engine. Neither opens a connection yet."""
        logger.info('Trying to connect to Postgres DB')
        if not self._connected:
            logger.info('Connecting to Postgres DB')
            self._engine = create_engine(self._db_url, **_POOL)
            self._SessionFactory = sessionmaker(
                bind=self._engine,
                future=True,
                expire_on_commit=False,
                query_cls=CustomQuery,
            )
            self._async_engine = create_async_engine(self._db_url, **_POOL)
            self._AsyncSessionFactory = async_sessionmaker(
                bind=self._async_engine, expire_on_commit=False
            )
            self._connected = True
        else:
            logger.warning('Not connecting. Connection with the DB already established')

    async def dispose(self):
        """Close the pooled connections of both engines."""
        if self._async_engine is not None:
            await self._async_engine.dispose()
        if self._engine is not None:
            self._engine.dispose()

    def reset_connection(self):
        logger.info('Resetting DB connection')
        self._engine = None
        self._SessionFactory = None
        self._async_engine = None
        self._AsyncSessionFactory = None
        self._connected = False

    async def init_mappings(self):
        logger.info('Initiating DB orm mappings')
        async with self._async_engine.connect() as conn:
            await conn.run_sync(Reflected.prepare, views=True)

    def begin_session(self) -> SessionScope:
        """One transaction. Use ``async with``: the sync ``with`` goes in Async 05."""
        return SessionScope(self)

    @property
    def db_url(self):
        return self._db_url
