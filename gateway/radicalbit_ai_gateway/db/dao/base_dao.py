from sqlalchemy.orm import object_mapper


class BaseDAO:
    def attributes(self):
        return {c.key: getattr(self, c.key) for c in object_mapper(self).column_attrs}
