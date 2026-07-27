"""Converts between the response_format the gateway always requests upstream
(to guarantee `usage`, see AG-835 — verbose_json for whisper-1, json for
gpt-4o-transcribe*) and the format the client actually asked for. Rejects
formats the invoked model family can't produce instead of silently degrading.
"""

from radicalbit_ai_gateway.utils.exceptions import ModelInvokerBadRequest

JSON_RESPONSE_FORMATS = {'json', 'verbose_json'}
TEXT_RESPONSE_FORMATS = {'text', 'srt', 'vtt'}
SUPPORTED_RESPONSE_FORMATS = JSON_RESPONSE_FORMATS | TEXT_RESPONSE_FORMATS


def _format_timestamp_srt(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f'{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}'


def _format_timestamp_vtt(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f'{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}'


def build_srt(segments: list) -> str:
    """Build an SRT subtitle body from a list of transcription segments."""
    lines = []
    for i, segment in enumerate(segments, start=1):
        lines.append(str(i))
        lines.append(
            f'{_format_timestamp_srt(segment.start)} --> {_format_timestamp_srt(segment.end)}'
        )
        lines.append(segment.text.strip())
        lines.append('')
    return '\n'.join(lines).strip() + '\n'


def build_vtt(segments: list) -> str:
    """Build a WebVTT subtitle body from a list of transcription segments."""
    lines = ['WEBVTT', '']
    for segment in segments:
        lines.append(
            f'{_format_timestamp_vtt(segment.start)} --> {_format_timestamp_vtt(segment.end)}'
        )
        lines.append(segment.text.strip())
        lines.append('')
    return '\n'.join(lines).strip() + '\n'


def convert_transcription_response(
    response,
    requested_format: str,
    is_whisper: bool,
) -> tuple[str | dict, str]:
    """Return (body, media_type); raise `ModelInvokerBadRequest` if the
    requested format needs capabilities the invoked model family lacks.
    """
    if requested_format not in SUPPORTED_RESPONSE_FORMATS:
        raise ModelInvokerBadRequest(
            f'Unsupported response_format {requested_format!r}. '
            f'Supported formats: {sorted(SUPPORTED_RESPONSE_FORMATS)}.'
        )

    if requested_format in JSON_RESPONSE_FORMATS and not is_whisper:
        if requested_format == 'verbose_json':
            raise ModelInvokerBadRequest(
                'response_format=verbose_json is only supported for whisper-1 models.'
            )
        return {'text': response.text, 'usage': response.usage}, 'application/json'

    if requested_format in TEXT_RESPONSE_FORMATS and not is_whisper:
        if requested_format == 'text':
            return response.text, 'text/plain'
        raise ModelInvokerBadRequest(
            f'response_format={requested_format!r} requires segment timing, only '
            'available for whisper-1 models.'
        )

    # is_whisper is True from here on: response has `segments`/`duration`/`language`.
    if requested_format == 'verbose_json':
        return response.model_dump(), 'application/json'
    if requested_format == 'json':
        return {'text': response.text, 'usage': response.usage}, 'application/json'
    if requested_format == 'text':
        return response.text, 'text/plain'
    if requested_format == 'srt':
        return build_srt(response.segments or []), 'text/plain'
    if requested_format == 'vtt':
        return build_vtt(response.segments or []), 'text/plain'

    raise ModelInvokerBadRequest(f'Unsupported response_format {requested_format!r}.')
