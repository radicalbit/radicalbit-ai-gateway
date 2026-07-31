from enum import Enum


class RequestType(str, Enum):
    CHAT_COMPLETIONS = 'chat_completions'
    EMBEDDINGS = 'embeddings'
    TRANSCRIPTIONS = 'transcriptions'
    MCP = 'mcp'


class RequestStatus(str, Enum):
    SUCCESS = 'success'
    HANDLED_ERROR = 'handled_error'
    UNHANDLED_ERROR = 'unhandled_error'
