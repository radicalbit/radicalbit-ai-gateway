from sqlalchemy import CursorResult, Delete, Update
from sqlalchemy.ext.asyncio import AsyncSession


async def rows_matched(session: AsyncSession, statement: Update | Delete) -> int:
    """Run an UPDATE or DELETE in the session and return the rows it matched."""
    result = await session.execute(statement)
    # AsyncSession.execute is typed for the result of a SELECT; an UPDATE or a
    # DELETE returns a CursorResult, which carries the row count.
    if not isinstance(result, CursorResult):
        raise TypeError(
            f'{type(statement).__name__} returned a {type(result).__name__}, '
            'not a CursorResult'
        )
    return result.rowcount
