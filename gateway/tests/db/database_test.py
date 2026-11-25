"""A database must be connected before it maps tables or opens sessions."""

import asyncio

import pytest

from radicalbit_ai_gateway.db.clickhouse_database import ClickHouseDatabase
from radicalbit_ai_gateway.db.database import Database
from radicalbit_ai_gateway.utils.app_config import ClickHouseConfig, DBConfig

NOT_CONNECTED = r'call connect\(\) first'


def test_a_database_not_connected_neither_maps_nor_opens_sessions():
    database = Database(DBConfig())

    async def open_async_session():
        async with database.begin_session():
            pass

    with pytest.raises(RuntimeError, match=NOT_CONNECTED):
        asyncio.run(database.init_mappings())
    with pytest.raises(RuntimeError, match=NOT_CONNECTED):
        asyncio.run(open_async_session())
    with pytest.raises(RuntimeError, match=NOT_CONNECTED), database.begin_session():
        pass


def test_a_clickhouse_database_not_connected_neither_maps_nor_opens_sessions():
    database = ClickHouseDatabase(ClickHouseConfig())

    with pytest.raises(RuntimeError, match=NOT_CONNECTED):
        database.init_mappings()
    with pytest.raises(RuntimeError, match=NOT_CONNECTED):
        database.begin_session()
