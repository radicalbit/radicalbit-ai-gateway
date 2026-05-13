from rich.console import Console
from rich.logging import RichHandler


def make_rich_handler():
    """Return a RichHandler that forces ANSI colors even when stdout/stderr
    is not a TTY (e.g., docker logs).
    """

    console = Console(
        force_terminal=True,
        width=150,
        soft_wrap=True,
    )

    return RichHandler(
        console=console,
        markup=False,
        rich_tracebacks=False,
        locals_max_string=150,
    )
