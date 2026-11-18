"""Readable labels for the spans of a trace.

The label is worked out when the trace tree is read. It is never written on
the span. So old traces get labels too, and a rename only changes this table.

Labels are English only.
"""

# Keyed by span name without the .workflow / .task suffix.
_SPAN_LABELS: dict[str, str] = {
    # Request
    'decision_model': 'Decision request',
    'chat_completions': 'Chat request',
    'responses': 'Responses request',
    'messages': 'Messages request',
    'embeddings': 'Embeddings request',
    'audio_transcriptions': 'Transcription request',
    'mcp_request': 'MCP request',
    # Access
    'auth_api_key': 'Authenticate credential',
    'check_route_access': 'Check route access',
    'check_limiters': 'Check limits',
    'check_embedding_limiters': 'Check limits',
    # Input
    'run_preprocessing': 'Preprocess request',
    'apply_check_guardrails': 'Input guardrails',
    'apply_redact_guardrails': 'Redaction',
    # Guardrail checks
    'check_regex': 'Regex guardrail',
    'check_contains': 'Contains guardrail',
    'check_starts_with': 'Starts-with guardrail',
    'check_ends_with': 'Ends-with guardrail',
    'presidio_analyzer': 'PII detection',
    'redact_presidio': 'PII redaction',
    'check_judge': 'LLM judge guardrail',
    'check_decision_judge': 'Decision judge guardrail',
    'check_guardrails_ai': 'Guardrails AI check',
    # Cache
    'get_semantic_cache': 'Cache lookup',
    'get_exact_cache': 'Cache lookup',
    'set_semantic_cache': 'Cache store',
    'set_exact_cache': 'Cache store',
    'get_in_memory_cache': 'Cache lookup',
    'set_in_memory_cache': 'Cache store',
    # Model
    'select_model': 'Select model',
    'select_embedding_model': 'Select embedding model',
    'select_transcription_model': 'Select transcription model',
    'llm_complete': 'Call model',
    'llm_complete_responses': 'Call model (Responses API)',
    'llm_complete_messages': 'Call model (Messages API)',
    'llm_stream': 'Stream from model',
    'llm_stream_responses': 'Stream from model (Responses API)',
    'llm_stream_messages': 'Stream from model (Messages API)',
    'llm_embed': 'Embed with model',
    'llm_transcribe': 'Transcribe with model',
    'llm_transcribe_stream': 'Stream transcription from model',
    'decide': 'Decide',
    # Output
    'apply_output_guardrails': 'Output guardrails',
    'apply_responses_output_guardrails': 'Output guardrails (Responses API)',
    'apply_messages_output_guardrails': 'Output guardrails (Messages API)',
    'stream_with_output_guardrails': 'Stream with output guardrails',
    # MCP
    'mcp_tools_call': 'MCP tool call',
    'mcp_upstream_call_tool': 'Upstream tool call',
    'mcp_initialize': 'MCP initialize',
    'mcp_tools_list': 'MCP list tools',
    'mcp_prompts_list': 'MCP list prompts',
    'mcp_prompts_get': 'MCP get prompt',
    'mcp_resources_list': 'MCP list resources',
    'mcp_resources_read': 'MCP read resource',
    'mcp_upstream_list_tools': 'Upstream list tools',
    'mcp_upstream_list_prompts': 'Upstream list prompts',
    'mcp_upstream_get_prompt': 'Upstream get prompt',
    'mcp_upstream_list_resources': 'Upstream list resources',
    'mcp_upstream_read_resource': 'Upstream read resource',
}

_PROVIDER_LABELS: dict[str, str] = {
    'openai': 'OpenAI request',
    'azure.ai.openai': 'Azure OpenAI request',
    'deepseek': 'DeepSeek request',
    'anthropic': 'Anthropic request',
    'gcp.gen_ai': 'Google Gemini request',
    'mistral_ai': 'Mistral AI request',
    'mock': 'Mock model request',
}

_SPAN_KIND_SUFFIXES = ('.workflow', '.task')
_PROVIDER_CALL_SUFFIX = '.chat'


def span_label(span_name: str, gen_ai_provider: str = '') -> str | None:
    """Return the readable label of a span, None for a name not in the table."""
    if span_name.endswith(_PROVIDER_CALL_SUFFIX):
        return _PROVIDER_LABELS.get(gen_ai_provider)
    for suffix in _SPAN_KIND_SUFFIXES:
        if span_name.endswith(suffix):
            span_name = span_name.removesuffix(suffix)
            break
    return _SPAN_LABELS.get(span_name)
