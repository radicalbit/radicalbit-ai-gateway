"""What the proxy endpoints share on the HTTP side: their decorators and
their server-sent events.
"""

from collections.abc import AsyncIterator
from functools import wraps
import json
import logging
import time

from fastapi import Request
from pydantic import BaseModel
from traceloop.sdk.decorators import workflow

from radicalbit_ai_gateway.endpoints.common.streaming_response import (
    StreamingResponseWithStatusCode,
)
from radicalbit_ai_gateway.metrics.define_metrics import (
    request_latency_histogram,
    total_requests_counter,
)
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import AppError, ModelInvokerUpstreamError
from radicalbit_ai_gateway.utils.request_context import reset_route_context
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    ensure_endpoint_category,
    in_request_trace,
    set_operation_category,
)

logger = logging.getLogger(get_app_config().log_config.logger_name)


def record_metrics(
    method: str,
    path: str,
    status_code: int,
    route_name: str,
    latency_ms: float,
    model_name: str | None = None,
):
    attributes = {
        'http.method': method,
        'http.route': path,
        'http.status_code': status_code,
        'route.name': route_name,
        'model_name': model_name,
    }
    request_latency_histogram.record(latency_ms, attributes=attributes)
    total_requests_counter.add(1, attributes=attributes)
    log_message = 'Metrics recorded for {} {}: status={}, route={}, latency={:.2f}ms'
    logger.debug(log_message.format(method, path, status_code, route_name, latency_ms))


def otel_metrics_decorator(func):
    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        start_time = time.monotonic()
        status_code = 200

        try:
            return await func(request, *args, **kwargs)
        except Exception:
            status_code = 500
            raise
        finally:
            # Get metrics data from request state (set by the decorated function)
            route_name = getattr(request.state, 'otel_route_name', 'unknown')
            model_name = getattr(request.state, 'otel_model_name', None)

            latency_ms = (time.monotonic() - start_time) * 1000
            record_metrics(
                request.method,
                request.url.path,
                status_code,
                route_name,
                latency_ms,
                model_name,
            )

    return wrapper


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
    after it, once the 200 is sent, is the stream's last event, as OpenAI
    streams one: ``data: {"error": ...}`` and no ``[DONE]``.
    """

    async def events():
        started = False

        def failed(body: str, code: int):
            return f'data: {body}\n\n' if started else (body, code)

        try:
            async for item in items:
                data = item.model_dump_json(exclude_none=True)
                logger.debug(item_log, data)
                started = True
                yield f'data: {data}\n\n'
            logger.debug(done_log)
            yield 'data: [DONE]\n\n'
        except ModelInvokerUpstreamError as exc:
            # The provider's refusal, as the provider sent it.
            yield failed(json.dumps(exc.body), exc.status_code)
        except AppError as exc:
            yield failed(
                *_error(exc.client_message, 'model_invoker_error', exc.status_code)
            )
        except Exception:
            logger.exception(error_log)
            yield failed(
                *_error('Unhandled error during streaming', 'internal_error', 500)
            )

    set_operation_category(OperationCategory.ENDPOINT)
    return StreamingResponseWithStatusCode(
        in_request_trace(events()), media_type='text/event-stream', headers=headers
    )


def _error(message: str, error_type: str, code: int) -> tuple[str, int]:
    body = {
        'error': {'message': message, 'type': error_type, 'param': None, 'code': code}
    }
    return json.dumps(body), code
