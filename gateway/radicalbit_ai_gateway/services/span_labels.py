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
    # Access
    'auth_api_key': 'Authenticate credential',
    'check_route_access': 'Check route access',
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
    # Model
    'select_model': 'Select model',
    'select_embedding_model': 'Select embedding model',
    'select_transcription_model': 'Select transcription model',
    'llm_complete': 'Call model',
    'llm_complete_responses': 'Call model (Responses API)',
    'llm_complete_messages': 'Call model (Messages API)',
    'llm_stream': 'Stream from model',
    'llm_embed': 'Embed with model',
    'llm_transcribe': 'Transcribe with model',
    'decide': 'Decide',
    # Output
    'apply_output_guardrails': 'Output guardrails',
    'stream_with_output_guardrails': 'Stream with output guardrails',
    # MCP
    'mcp_tools_call': 'MCP tool call',
    'mcp_upstream_call_tool': 'Upstream tool call',
}

_SPAN_KIND_SUFFIXES = ('.workflow', '.task')


def span_label(span_name: str) -> str | None:
    """Return the readable label of a span, None for a name not in the table."""
    for suffix in _SPAN_KIND_SUFFIXES:
        if span_name.endswith(suffix):
            span_name = span_name.removesuffix(suffix)
            break
    return _SPAN_LABELS.get(span_name)
