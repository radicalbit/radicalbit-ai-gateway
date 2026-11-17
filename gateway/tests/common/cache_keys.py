"""The cache keys the gateway stores entries under, by endpoint."""

from radicalbit_ai_gateway.caching.route_cache import cache_key
from radicalbit_ai_gateway.endpoints.chat_completions.cache import ChatEntry
from radicalbit_ai_gateway.endpoints.embeddings.cache import EmbeddingEntry
from radicalbit_ai_gateway.endpoints.transcriptions.cache import TranscriptionEntry


def chat_key(
    project_uuid: str,
    route_name: str,
    key_uuid: str,
    messages: list,
    tools=None,
    tool_choice=None,
    **params,
) -> str:
    return cache_key(
        project_uuid,
        route_name,
        key_uuid,
        ChatEntry(messages, tools, tool_choice, params),
    )


def embedding_key(
    project_uuid: str, route_name: str, key_uuid: str, input_texts: list[str]
) -> str:
    return cache_key(project_uuid, route_name, key_uuid, EmbeddingEntry(input_texts))


def transcription_key(
    project_uuid: str,
    route_name: str,
    key_uuid: str,
    audio_bytes: bytes,
    model_id: str,
    response_format: str,
    language: str | None = None,
    prompt: str | None = None,
    temperature: float | None = None,
) -> str:
    return cache_key(
        project_uuid,
        route_name,
        key_uuid,
        TranscriptionEntry(
            audio_bytes, model_id, response_format, language, prompt, temperature
        ),
    )
