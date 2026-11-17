"""Server-sent events, as the providers' streaming APIs send them."""

from collections.abc import AsyncIterator
import json


async def iter_sse_events(lines: AsyncIterator[str]) -> AsyncIterator[tuple[str, str]]:
    """Parse server-sent event lines into ``(event, data)`` pairs.

    An event without an ``event:`` field takes its name from the data's
    ``type``, as every Responses and Messages API stream event carries one.
    A ``[DONE]`` terminator, which OpenAI does not send but compatible servers
    may, is skipped.
    """
    event = ''
    data: list[str] = []
    async for line in lines:
        if line.startswith('event:'):
            event = line[6:].strip()
        elif line.startswith('data:'):
            data.append(line[5:].removeprefix(' '))
        elif not line and data:
            payload = '\n'.join(data)
            if payload != '[DONE]':
                yield event or json.loads(payload).get('type', ''), payload
            event, data = '', []
    if data and data != ['[DONE]']:
        payload = '\n'.join(data)
        yield event or json.loads(payload).get('type', ''), payload
