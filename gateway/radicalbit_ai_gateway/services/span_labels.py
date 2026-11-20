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
    'load_project_limits': 'Load project limits',
    'check_request_rate': 'Request rate limit',
    'check_token_input_limit': 'Input token limit',
    'check_token_input_room': 'Input token limit',
    'check_token_output_limit': 'Output token limit',
    'check_budget_limit': 'Budget limit',
    'check_audio_duration_limit': 'Audio duration limit',
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
    'lookup_cache': 'Check cache',
    'lookup_responses_cache': 'Check cache',
    'lookup_messages_cache': 'Check cache',
    'get_cached_response': 'Read cached response',
    'generate_semantic_cache_embedding': 'Embed for semantic cache',
    'set_cached_response': 'Store response in cache',
    'set_cached_stream_response': 'Store streamed response in cache',
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
# One span per preprocessing plugin, named after the plugin's config key.
_PLUGIN_PREFIX = 'preprocess.'


def span_label(span_name: str, gen_ai_provider: str = '') -> str | None:
    """Return the readable label of a span, None for a name not in the table."""
    if span_name.endswith(_PROVIDER_CALL_SUFFIX):
        return _PROVIDER_LABELS.get(gen_ai_provider)
    for suffix in _SPAN_KIND_SUFFIXES:
        if span_name.endswith(suffix):
            span_name = span_name.removesuffix(suffix)
            break
    if span_name.startswith(_PLUGIN_PREFIX):
        return f'Preprocessing plugin: {span_name.removeprefix(_PLUGIN_PREFIX)}'
    return _SPAN_LABELS.get(span_name)
