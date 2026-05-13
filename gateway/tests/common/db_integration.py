from typing import TypeVar
import unittest

from testcontainers.postgres import PostgresContainer

from radicalbit_ai_gateway.db import database
from radicalbit_ai_gateway.db.database import Database
from radicalbit_ai_gateway.utils.app_config import DBConfig

T = TypeVar('T')


class DatabaseIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.postgres_container = PostgresContainer(image='postgres:15')
        cls.postgres_container.start()
        cls.db_conf = DBConfig()
        cls.db = Database(conf=cls.db_conf)
        cls.db._db_url = cls.postgres_container.get_connection_url()
        cls.db.connect()
        with cls.db._engine.connect() as conn:
            conn.commit()
        database.BaseTable.metadata.create_all(cls.db._engine)
        cls.db.init_mappings()

    @classmethod
    def tearDownClass(cls) -> None:
        # Drop schema at class end
        database.BaseTable.metadata.drop_all(cls.db._engine)
        # Sanitize possible duplicated/reflected UNIQUE constraints left in metadata
        cls._sanitize_unique_constraints()
        cls.db.reset_connection()
        cls.postgres_container.stop()

    @classmethod
    def _sanitize_unique_constraints(cls) -> None:
        """Remove duplicated UNIQUE constraints that may have been added by reflection.
        This avoids re-emitting both UNIQUE and UNIQUE NULLS DISTINCT on the same columns.
        """
        for table in list(database.BaseTable.metadata.tables.values()):
            seen: set[tuple[str, tuple[str, ...]]] = set()
            to_remove = []
            for constraint in list(table.constraints):
                if type(constraint).__name__ == 'UniqueConstraint':
                    name = constraint.name or ''
                    cols = tuple(col.name for col in constraint.columns)
                    key = (name, cols)
                    # Remove if duplicated by name+columns
                    if key in seen:
                        to_remove.append(constraint)
                        continue
                    seen.add(key)
                    # Remove dialect-added variants like NULLS DISTINCT if detected
                    dialect_kwargs = getattr(constraint, 'dialect_kwargs', {}) or {}
                    if any('nulls' in k for k in dialect_kwargs):
                        to_remove.append(constraint)
            for c in to_remove:
                table.constraints.remove(c)

    def tearDown(self):
        with self.db.begin_session() as session:
            for table in reversed(database.BaseTable.metadata.sorted_tables):
                session.execute(table.delete())
            session.commit()

    def insert(self, table: T) -> T:
        with self.db.begin_session() as session:
            session.add(table)
            session.flush()
            return table
