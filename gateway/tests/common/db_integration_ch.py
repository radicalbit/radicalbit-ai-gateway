import logging
from typing import TypeVar
import unittest

from sqlalchemy import text
from testcontainers.clickhouse import ClickHouseContainer

from radicalbit_ai_gateway.db.clickhouse_database import (
    ClickHouseBaseTable,
    ClickHouseDatabase,
)
from radicalbit_ai_gateway.db.tables.event_table import Event
from radicalbit_ai_gateway.db.tables.otel_traces_table import OtelTraces
from radicalbit_ai_gateway.db.tables.request_event_table import RequestEvent
from radicalbit_ai_gateway.utils.app_config import ClickHouseConfig, get_app_config

T = TypeVar('T')

logger = logging.getLogger(get_app_config().log_config.logger_name)


class DatabaseIntegrationClickhouse(unittest.TestCase):
    container = None
    engine = None

    @classmethod
    def setUpClass(cls):
        cls.container = ClickHouseContainer(
            'clickhouse/clickhouse-server:25.12',
            port=9000,
            username='default',
            password='default',
            dbname='default',
        )
        cls.container.start()
        cls.db_conf = ClickHouseConfig(
            clickhouse_db_host='localhost',
            clickhouse_db_port=cls.container.get_exposed_port(9000),
            clickhouse_db_user='default',
            clickhouse_db_pwd='default',
            clickhouse_db_name='default',
        )
        cls.db = ClickHouseDatabase(conf=cls.db_conf)
        cls.db.connect()
        ClickHouseBaseTable.metadata.create_all(cls.db._engine)

    def setUp(self):
        pass

    def tearDown(self) -> None:
        self.clean()

    @classmethod
    def tearDownClass(cls):
        # Stop container after all tests are complete
        if cls.container:
            cls.container.stop()
            cls.container = None
            cls.db = None

    def insert(self, table: list[T]):
        """Insert objects into the database.

        Note: OtelTraces objects use raw SQL because clickhouse-driver doesn't
        handle dot-notation column names correctly with ORM inserts.
        """
        if not table:
            return

        # Check if any objects are OtelTraces
        if isinstance(table[0], OtelTraces):
            self._insert_otel_traces(table)
        else:
            with self.db.begin_session() as session:
                for obj in table:
                    session.add(obj)
                session.commit()

    def _insert_otel_traces(self, traces: list[OtelTraces]):
        """Insert OtelTraces using raw SQL.

        clickhouse-sqlalchemy doesn't support column names with dots (e.g., 'Events.Timestamp')
        in ORM or Core insert() statements. Raw SQL with text() is required.
        """
        with self.db.begin_session() as session:
            for trace in traces:
                session.execute(
                    text("""
                        INSERT INTO otel_traces (
                            Timestamp, TraceId, SpanId, ParentSpanId, TraceState,
                            SpanName, SpanKind, ServiceName, ResourceAttributes,
                            ScopeName, ScopeVersion, SpanAttributes, Duration,
                            StatusCode, StatusMessage,
                            `Events.Timestamp`, `Events.Name`, `Events.Attributes`
                        ) VALUES (
                            :timestamp, :trace_id, :span_id, :parent_span_id, :trace_state,
                            :span_name, :span_kind, :service_name, :resource_attributes,
                            :scope_name, :scope_version, :span_attributes, :duration,
                            :status_code, :status_message,
                            :events_timestamp, :events_name, :events_attributes
                        )
                    """),
                    {
                        'timestamp': trace.timestamp,
                        'trace_id': trace.trace_id,
                        'span_id': trace.span_id,
                        'parent_span_id': trace.parent_span_id,
                        'trace_state': trace.trace_state,
                        'span_name': trace.span_name,
                        'span_kind': trace.span_kind,
                        'service_name': trace.service_name,
                        'resource_attributes': trace.resource_attributes,
                        'scope_name': trace.scope_name,
                        'scope_version': trace.scope_version,
                        'span_attributes': trace.span_attributes,
                        'duration': trace.duration,
                        'status_code': trace.status_code,
                        'status_message': trace.status_message,
                        'events_timestamp': trace.events_timestamp,
                        'events_name': trace.events_name,
                        'events_attributes': trace.events_attributes,
                    },
                )
            session.commit()

    def clean(self):
        with self.db.begin_session() as session:
            session.execute(text(f'TRUNCATE TABLE {Event.__tablename__}'))
            session.execute(text(f'TRUNCATE TABLE {RequestEvent.__tablename__}'))
            session.execute(text(f'TRUNCATE TABLE {OtelTraces.__tablename__}'))
            session.commit()
