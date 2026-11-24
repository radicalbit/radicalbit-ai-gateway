"""A database must be connected before it maps tables or opens sessions."""

import pytest

from radicalbit_ai_gateway.db.clickhouse_database import ClickHouseDatabase
from radicalbit_ai_gateway.db.database import Database
from radicalbit_ai_gateway.utils.app_config import ClickHouseConfig, DBConfig


@pytest.mark.parametrize(
    'database',
    [
        pytest.param(Database(DBConfig()), id='database'),
        pytest.param(ClickHouseDatabase(ClickHouseConfig()), id='clickhouse'),
    ],
)
def test_a_database_not_connected_neither_maps_nor_opens_sessions(
    database: Database | ClickHouseDatabase,
):
    with pytest.raises(RuntimeError, match=r'call connect\(\) first'):
        database.init_mappings()
    with pytest.raises(RuntimeError, match=r'call connect\(\) first'):
        database.begin_session()
