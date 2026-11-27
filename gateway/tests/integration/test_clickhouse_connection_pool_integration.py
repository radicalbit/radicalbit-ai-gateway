"""The ClickHouse HTTP pool on real ClickHouse.

The HTTP pool keeps a connection for every session SQLAlchemy may open at
once, so none is discarded and reopened under load.
"""

from concurrent.futures import ThreadPoolExecutor
import logging
import threading

from sqlalchemy import text

from tests.common.db_integration_ch import DatabaseIntegrationClickhouse

AT_ONCE = 15  # SQLAlchemy's default pool: 5, plus 10 overflow


class TestClickHouseConnectionPoolIntegration(DatabaseIntegrationClickhouse):
    def test_as_many_queries_at_once_as_sqlalchemy_allows_keep_every_connection(self):
        # urllib3 warns "Connection pool is full, discarding connection" for each
        # connection it drops. The gateway's logging config disables urllib3's
        # logger, so turn it back on to hear it.
        urllib3_log = logging.getLogger('urllib3.connectionpool')
        was_disabled = urllib3_log.disabled
        urllib3_log.disabled = False
        self.addCleanup(setattr, urllib3_log, 'disabled', was_disabled)
        # All the queries start together, so each needs its own HTTP connection.
        start = threading.Barrier(AT_ONCE)

        def query(_):
            with self.db.begin_session() as session:
                start.wait(timeout=30)
                return session.execute(text('SELECT sleep(0.5)')).scalar()

        with (
            self.assertNoLogs('urllib3', level='WARNING'),
            ThreadPoolExecutor(max_workers=AT_ONCE) as pool,
        ):
            results = list(pool.map(query, range(AT_ONCE)))

        assert len(results) == AT_ONCE
