import atexit
import functools
import logging
from typing import TypeVar
import unittest

from clickhouse_connect import common as clickhouse_common
from sqlalchemy import text
from testcontainers.community.clickhouse import ClickHouseContainer

from radicalbit_ai_gateway.db.clickhouse_database import (
    ClickHouseBaseTable,
    ClickHouseDatabase,
)
from radicalbit_ai_gateway.db.tables.alert_table import Alert
from radicalbit_ai_gateway.db.tables.event_table import Event
from radicalbit_ai_gateway.db.tables.otel_traces_table import OtelTraces
from radicalbit_ai_gateway.db.tables.request_event_table import RequestEvent
from radicalbit_ai_gateway.utils.app_config import ClickHouseConfig, get_app_config

T = TypeVar('T')

# The tests insert dicts into Map columns: bind them as ClickHouse maps, not JSON.
clickhouse_common.set_setting('dict_parameter_format', 'map')

logger = logging.getLogger(get_app_config().log_config.logger_name)


@functools.cache
def _clickhouse() -> ClickHouseContainer:
    """Start one ClickHouse for the test run: starting one takes seconds, and
    each test empties its tables when it ends.
    """
    container = ClickHouseContainer(
        'clickhouse/clickhouse-server:25.12',
        port=9000,
        username='default',
        password='default',
        dbname='default',
    )
    container.start()
    atexit.register(container.stop)
    return container


class DatabaseIntegrationClickhouse(unittest.TestCase):
    container = None
    engine = None
    # Subclasses that build the schema themselves (e.g. from the ClickHouse
    # migrations) turn this off.
    create_orm_schema = True

    @classmethod
    def setUpClass(cls):
        cls.container = _clickhouse()
        cls.db_conf = ClickHouseConfig(
            clickhouse_db_host='localhost',
            clickhouse_db_http_port=cls.container.get_exposed_port(8123),
            clickhouse_db_user='default',
            clickhouse_db_pwd='default',
            clickhouse_db_name='default',
        )
        cls.db = ClickHouseDatabase(conf=cls.db_conf)
        cls.db.connect()
        if cls.create_orm_schema:
            ClickHouseBaseTable.metadata.create_all(cls.db._engine)

    def setUp(self):
        pass

    def tearDown(self) -> None:
        self.clean()

    @classmethod
    def tearDownClass(cls):
        # Close the pooled connections: reset_connection only drops the engine.
        cls.db._engine.dispose()
        cls.container = None
        cls.db = None

    def insert(self, table: list[T]):
        """Insert objects into the database."""
        if not table:
            return
        with self.db.begin_session() as session:
            for obj in table:
                session.add(obj)
            session.commit()

    def clean(self):
        with self.db.begin_session() as session:
            session.execute(text(f'TRUNCATE TABLE {Event.__tablename__}'))
            session.execute(text(f'TRUNCATE TABLE {RequestEvent.__tablename__}'))
            session.execute(text(f'TRUNCATE TABLE {OtelTraces.__tablename__}'))
            session.execute(text(f'TRUNCATE TABLE {Alert.__tablename__}'))
            session.commit()
