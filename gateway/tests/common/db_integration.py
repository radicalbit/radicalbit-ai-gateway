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

        `table.constraints` is a set, so iteration order is not deterministic.
        Grouping by (name, cols) before deciding which copy to keep avoids a
        prior bug where, depending on iteration order, both the declared and
        the reflected copy of a constraint could independently match removal
        criteria and both end up removed, dropping the constraint entirely.
        """
        for table in list(database.BaseTable.metadata.tables.values()):
            groups: dict[tuple[str, tuple[str, ...]], list] = {}
            for constraint in table.constraints:
                if type(constraint).__name__ != 'UniqueConstraint':
                    continue
                name = constraint.name or ''
                cols = tuple(col.name for col in constraint.columns)
                groups.setdefault((name, cols), []).append(constraint)

            def _has_nulls_kwarg(constraint) -> bool:
                dialect_kwargs = getattr(constraint, 'dialect_kwargs', {}) or {}
                return any('nulls' in k for k in dialect_kwargs)

            to_remove = []
            for constraints in groups.values():
                # Prefer to keep a copy with no dialect-added NULLS variant
                # (the declared one); fall back to an arbitrary copy so a
                # constraint is never dropped entirely.
                survivor = next(
                    (c for c in constraints if not _has_nulls_kwarg(c)),
                    constraints[0],
                )
                to_remove.extend(c for c in constraints if c is not survivor)

            for c in to_remove:
                table.constraints.remove(c)

            # Remove duplicate indexes (by name) that reflection may have
            # re-added alongside model-declared ones (e.g. partial unique
            # indexes), which would make a later create_all emit them twice.
            seen_idx: set[str] = set()
            for index in list(table.indexes):
                if index.name in seen_idx:
                    table.indexes.discard(index)
                else:
                    seen_idx.add(index.name)

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
