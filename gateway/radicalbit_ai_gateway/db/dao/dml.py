from sqlalchemy import CursorResult, Delete, Update
from sqlalchemy.orm import Session


def rows_matched(session: Session, statement: Update | Delete) -> int:
    """Run an UPDATE or DELETE in the session and return the rows it matched."""
    result = session.execute(statement)
    # Session.execute is typed for the result of a SELECT; an UPDATE or a
    # DELETE returns a CursorResult, which carries the row count.
    if not isinstance(result, CursorResult):
        raise TypeError(
            f'{type(statement).__name__} returned a {type(result).__name__}, '
            'not a CursorResult'
        )
    return result.rowcount
