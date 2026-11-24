import logging

from clickhouse_connect.driver.httputil import get_pool_manager
from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine.url import URL
from sqlalchemy.ext.declarative import DeferredReflection
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from radicalbit_ai_gateway.utils.app_config import ClickHouseConfig, get_app_config

logger = logging.getLogger(get_app_config().log_config.logger_name)

# HTTP connections kept open to ClickHouse.
HTTP_POOL_SIZE = 16


class Reflected(DeferredReflection):
    __abstract__ = True


ClickHouseBaseTable = declarative_base(metadata=MetaData(schema='default'))


class ClickHouseDatabase:
    def __init__(self, conf: ClickHouseConfig):
        self._db_url = URL.create(
            drivername='clickhousedb',
            username=conf.clickhouse_db_user,
            password=conf.clickhouse_db_pwd,
            host=conf.clickhouse_db_host,
            port=conf.clickhouse_db_http_port,
            database=conf.clickhouse_db_name,
        )
        self._engine = None
        self._SessionFactory = None
        self._connected = False

    def connect(self):
        logger.info('Trying to connect to Clickhouse DB')
        if not self._connected:
            logger.info('Connecting to the Clickhouse DB')
            # tz_mode='schema': a column declared with a timezone reads back
            # tz-aware, instead of the driver's default naive UTC.
            # pool_mgr: one HTTP pool, shared by every connection, with room for
            # all SQLAlchemy may open (5 + 10 overflow). The driver's default
            # pool keeps 8 and discards the rest, so under load they reopen.
            self._engine = create_engine(
                self._db_url,
                pool_pre_ping=True,
                connect_args={
                    'tz_mode': 'schema',
                    'pool_mgr': get_pool_manager(maxsize=HTTP_POOL_SIZE),
                },
            )
            self._SessionFactory = sessionmaker(bind=self._engine)
            self._connected = True
        else:
            logger.warning('Not connecting. Connection with the DB already established')

    def reset_connection(self):
        logger.info('Resetting DB connection')
        self._engine = None
        self._SessionFactory = None
        self._connected = False

    def init_mappings(self):
        logger.info('Initiating DB orm mappings')
        Reflected.prepare(self._engine)

    def begin_session(self) -> Session:
        return self._SessionFactory()

    @property
    def db_url(self):
        return self._db_url
