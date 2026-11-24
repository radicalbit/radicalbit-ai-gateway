from abc import ABC
from typing import Any

from sqlalchemy.orm import Query


class CustomQuery(Query[Any], ABC):
    def filter_if(self: Query[Any], condition: bool, *criterion):
        if condition:
            return self.filter(*criterion)
        return self
