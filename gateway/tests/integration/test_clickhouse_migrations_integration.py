"""The ClickHouse migrations, applied as goose applies them, on real ClickHouse."""

from pathlib import Path
import time
import uuid

from sqlalchemy import text

from tests.common.db_integration_ch import DatabaseIntegrationClickhouse

MIGRATIONS_DIR = (
    Path(__file__).resolve().parents[3] / 'clickhouse-migrations' / 'migrations'
)


def _up_statements(migration: Path) -> list[str]:
    """Return the statements of the `-- +goose Up` section of a migration."""
    up = migration.read_text().split('-- +goose Up', 1)[1]
    up = up.split('-- +goose Down', 1)[0]
    lines = [line for line in up.splitlines() if not line.strip().startswith('--')]
    return [stmt.strip() for stmt in '\n'.join(lines).split(';') if stmt.strip()]


class TestClickHouseMigrations(DatabaseIntegrationClickhouse):
    create_orm_schema = False

    def migrate(self, until: str | None = None):
        """Apply the migrations in order, stopping before the one named `until`."""
        for migration in sorted(MIGRATIONS_DIR.glob('*.sql')):
            if until and migration.name.startswith(until):
                return
            for stmt in _up_statements(migration):
                self.execute(stmt)

    def execute(self, sql: str, **params):
        with self.db.begin_session() as session:
            result = session.execute(text(sql), params).fetchall()
            session.commit()
            return result

    def wait_for_mutations(self, timeout: float = 30.0):
        deadline = time.monotonic() + timeout
        while self.execute(
            "SELECT count() FROM system.mutations WHERE database = 'default' "
            'AND is_done = 0'
        )[0][0]:
            assert time.monotonic() < deadline, 'mutations did not finish'
            time.sleep(0.2)

    def request_uuid_index(self, table: str = 'event'):
        return self.execute(
            'SELECT name, type, granularity FROM system.data_skipping_indices '
            "WHERE database = 'default' AND table = :table "
            "AND expr = 'REQUEST_UUID'",
            table=table,
        )

    def granules_after_lookup(
        self, request_uuid: uuid.UUID, table: str = 'event'
    ) -> str:
        """Return the `Granules: kept/total` line of the request UUID skip index."""
        plan = [
            row[0]
            for row in self.execute(
                # `table` is one of this file's own table names, never input.
                f'EXPLAIN indexes = 1 SELECT count() FROM default.{table} '  # noqa: S608
                'WHERE REQUEST_UUID = :request_uuid',
                request_uuid=str(request_uuid),
            )
        ]
        start = next(i for i, line in enumerate(plan) if 'idx_request_uuid' in line)
        return next(line.strip() for line in plan[start:] if 'Granules' in line)

    def clean(self):
        for (name,) in self.execute(
            "SELECT name FROM system.tables WHERE database = 'default'"
        ):
            self.execute(f'DROP TABLE IF EXISTS default.`{name}` SYNC')

    def test_fresh_database_gets_a_bloom_filter_index_on_request_uuid(self):
        self.migrate()

        assert self.request_uuid_index() == [('idx_request_uuid', 'bloom_filter', 1)]

    def test_index_is_materialized_for_events_stored_before_the_migration(self):
        self.migrate(until='013')
        for _ in range(3):
            self.execute(
                'INSERT INTO default.event (REQUEST_UUID, TIMESTAMP, EVENT_TYPE) '
                "VALUES (generateUUIDv4(), now64(9, 'UTC'), 'input_tokens')"
            )

        self.migrate()
        self.wait_for_mutations()

        assert self.request_uuid_index() == [('idx_request_uuid', 'bloom_filter', 1)]
        # A lookup of an unknown request UUID drops every granule of the old
        # parts, which only happens once the index is built for them.
        assert self.granules_after_lookup(uuid.uuid4()) == 'Granules: 0/3'

    def test_fresh_database_gets_a_bloom_filter_index_on_request_event(self):
        self.migrate()

        assert self.request_uuid_index('request_event') == [
            ('idx_request_uuid', 'bloom_filter', 1)
        ]

    def test_request_event_index_is_materialized_for_requests_already_stored(self):
        self.migrate(until='014')
        # Two routes in each part: the primary key, which leads with
        # ROUTE_NAME, cannot rule a request UUID out, only the skip index can.
        for _ in range(3):
            self.execute(
                'INSERT INTO default.request_event '
                '(REQUEST_UUID, TIMESTAMP, ROUTE_NAME) VALUES '
                "(generateUUIDv4(), now64(9, 'UTC'), 'route-a'), "
                "(generateUUIDv4(), now64(9, 'UTC'), 'route-b')"
            )

        self.migrate()
        self.wait_for_mutations()

        # Opening an unknown request drops every granule of the old parts,
        # which only happens once the index is built for them.
        assert (
            self.granules_after_lookup(uuid.uuid4(), 'request_event') == 'Granules: 0/3'
        )
