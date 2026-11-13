"""Types shared by the client and the generated resources."""

from collections.abc import Mapping
from typing import IO, Literal

# One file of a multipart body: an open file, or (filename, content[, content
# type[, headers]]). Not the content alone, which httpx2 sends with the filename
# "upload": the gateway reads the file type from the filename.
FileContent = IO[bytes] | bytes | str
FileTypes = (
    IO[bytes]
    | tuple[str, FileContent]
    | tuple[str, FileContent, str | None]
    | tuple[str, FileContent, str | None, Mapping[str, str]]
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
