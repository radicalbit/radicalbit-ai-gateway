"""Types shared by the client and the generated resources."""

from collections.abc import Mapping
from typing import IO, Literal

# What httpx2 accepts for one file of a multipart body: the content alone, or
# (filename, content[, content type[, headers]]).
FileContent = IO[bytes] | bytes | str
FileTypes = (
    FileContent
    | tuple[str | None, FileContent]
    | tuple[str | None, FileContent, str | None]
    | tuple[str | None, FileContent, str | None, Mapping[str, str]]
)


class NotGiven:
    """The default of every optional argument: the field or parameter is not sent.

    It tells "not given" apart from ``None``, which is sent as JSON ``null``.
    """

    def __bool__(self) -> Literal[False]:
        return False

    def __repr__(self) -> str:
        return 'NOT_GIVEN'


NOT_GIVEN = NotGiven()
