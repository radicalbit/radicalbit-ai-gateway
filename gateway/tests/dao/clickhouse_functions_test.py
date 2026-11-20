from sqlalchemy import func as F, select

from tests.common.db_integration_ch import DatabaseIntegrationClickhouse

from radicalbit_ai_gateway.db.clickhouse_functions import quantile


class ClickHouseFunctionsTest(DatabaseIntegrationClickhouse):
    def _quantiles(self, *levels: float) -> list[float]:
        values = F.arrayJoin(F.array(1, 5, 9))
        stmt = select(*(quantile(level, values) for level in levels))
        with self.db.begin_session() as session:
            return list(session.execute(stmt).one())

    def test_quantile_reads_each_level(self):
        assert self._quantiles(0.0, 0.5, 1.0) == [1.0, 5.0, 9.0]

    def test_each_level_has_its_own_cache_key(self):
        # SQLAlchemy reuses a compiled statement for an equal cache key: with
        # one key for every level, a query would run another level's SQL.
        # The ClickHouse dialect caches nothing today, so compare the keys.
        values = F.arrayJoin(F.array(1, 5, 9))
        p50, p99 = quantile(0.5, values), quantile(0.99, values)

        assert p50._generate_cache_key() != p99._generate_cache_key()
