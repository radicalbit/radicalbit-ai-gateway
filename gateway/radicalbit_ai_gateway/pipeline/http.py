"""What the proxy endpoints share on the HTTP side: their decorators and
their server-sent events.
"""

from collections.abc import AsyncIterator
import json
import logging

from pydantic import BaseModel
from traceloop.sdk.decorators import workflow

from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.endpoint_helpers import otel_metrics_decorator
from radicalbit_ai_gateway.utils.exceptions import AppError, ModelInvokerUpstreamError
from radicalbit_ai_gateway.utils.request_context import reset_route_context
from radicalbit_ai_gateway.utils.streaming_response import (
    StreamingResponseWithStatusCode,
)
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    ensure_endpoint_category,
    in_request_trace,
    set_operation_category,
)

logger = logging.getLogger(get_app_config().log_config.logger_name)


def endpoint(name: str):
    """Decorate a proxy endpoint: its HTTP metrics, its trace (a workflow
    span named ``name``, marked ENDPOINT), and the route context cleared when
    the request is done.
    """

    def decorate(handler):
        return otel_metrics_decorator(
            workflow(name=name)(ensure_endpoint_category(reset_route_context(handler)))
        )

    return decorate


def sse_response(
    items: AsyncIterator[BaseModel],
    headers: dict[str, str] | None = None,
    *,
    item_log: str = 'Streaming chunk: %s',
    done_log: str = 'Streaming finished: [DONE]',
    error_log: str = 'Unhandled error during streaming',
) -> StreamingResponseWithStatusCode:
    """Return ``items`` as server-sent events, then ``[DONE]``.

    An error before the first event answers with its status and body; one
    after it ends the stream.
    """

    async def events():
        try:
            async for item in items:
                data = item.model_dump_json(exclude_none=True)
                logger.debug(item_log, data)
                yield f'data: {data}\n\n'
            logger.debug(done_log)
            yield 'data: [DONE]\n\n'
        except ModelInvokerUpstreamError as exc:
            # The provider's refusal, as the provider sent it.
            yield json.dumps(exc.body), exc.status_code
        except AppError as exc:
            yield _error(exc.client_message, 'model_invoker_error', exc.status_code)
        except Exception:
            logger.exception(error_log)
            yield _error('Unhandled error during streaming', 'internal_error', 500)

    set_operation_category(OperationCategory.ENDPOINT)
    return StreamingResponseWithStatusCode(
        in_request_trace(events()), media_type='text/event-stream', headers=headers
    )


def _error(message: str, error_type: str, code: int) -> tuple[str, int]:
    body = {
        'error': {'message': message, 'type': error_type, 'param': None, 'code': code}
    }
    return json.dumps(body), code
