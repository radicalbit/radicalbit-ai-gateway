"""ClickHouse SQL functions that SQLAlchemy's `func` cannot express."""

from sqlalchemy import ColumnElement, literal_column
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.compiler import SQLCompiler
from sqlalchemy.sql.functions import FunctionElement
from sqlalchemy.types import Float


class quantile(FunctionElement):  # noqa: N801 - named after the SQL function
    """ClickHouse's parametric `quantile(level)(expr)`.

    `func.quantile(level, expr)` would render `quantile(level, expr)`, which
    ClickHouse rejects: the level is a parameter, in its own parentheses.
    """

    type = Float()
    inherit_cache = True

    def __init__(self, level: float, expr: ColumnElement):
        # The level is SQL text, not a bound value: it is then part of the
        # statement cache key, so two levels never share a compiled statement.
        super().__init__(literal_column(repr(float(level))), expr)


@compiles(quantile)
def _compile_quantile(element: quantile, compiler: SQLCompiler, **kw) -> str:
    level, expr = element.clauses
    return f'quantile({compiler.process(level, **kw)})({compiler.process(expr, **kw)})'
