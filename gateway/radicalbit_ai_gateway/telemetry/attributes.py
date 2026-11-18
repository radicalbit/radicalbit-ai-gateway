"""Names the gateway's telemetry puts on the wire.

The ``traceloop.*`` names date from when the gateway used the OpenLLMetry SDK.
They are the gateway's own now and are kept as they are: the trace queries, the
UI, the enterprise plugins and whatever reads the gateway's OTLP export rely
on them.
"""

# The instrumentation scope of the workflow and task spans.
TRACER_NAME = 'traceloop.tracer'

SPAN_KIND = 'traceloop.span.kind'
ENTITY_NAME = 'traceloop.entity.name'
ENTITY_INPUT = 'traceloop.entity.input'
ENTITY_OUTPUT = 'traceloop.entity.output'
ENTITY_PATH = 'traceloop.entity.path'
WORKFLOW_NAME = 'traceloop.workflow.name'
ASSOCIATION_PROPERTIES = 'traceloop.association.properties'

USAGE_TOTAL_TOKENS = 'gen_ai.usage.total_tokens'
TASK_STATUS = 'gen_ai.task.status'

OPERATION_DURATION_METRIC = 'gen_ai.client.operation.duration'
TOKEN_USAGE_METRIC = 'gen_ai.client.token.usage'
