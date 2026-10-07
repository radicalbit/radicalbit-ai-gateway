"""Helpers shared by the /v1 proxy endpoints, in server.py and in routes/."""

from functools import wraps
import logging
import time

from fastapi import Request
from traceloop.sdk.decorators import task

from radicalbit_ai_gateway.ai_gateway import GatewayRoute
from radicalbit_ai_gateway.auth.request_auth import authenticate_bearer_request
from radicalbit_ai_gateway.metrics.define_metrics import (
    request_latency_histogram,
    total_requests_counter,
)
from radicalbit_ai_gateway.models.auth_dto import KeyDetails
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.request_context import get_current_request_tags
from radicalbit_ai_gateway.utils.trace_attributes import set_trace_attributes

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


@task(name='auth_api_key')
async def set_api_key_uuid(
    request: Request, project_uuid: str, project_name: str
) -> KeyDetails:
    return await authenticate_bearer_request(request, project_uuid, project_name)


def set_early_project_trace_attributes(
    request: Request,
    route_key: str | None,
    route: GatewayRoute | None,
) -> None:
    """Set project identity on the span before route validation and auth.

    Ensures traces from failed requests (unknown route, bad API key) remain
    visible in project-scoped queries.
    """
    if route is not None:
        set_trace_attributes(
            project_uuid=route.project_uuid,
            project_name=route.project_name,
            tags=list(get_current_request_tags()),
        )
        return
    project_name, _, route_name_part = (route_key or '').partition('/')
    entry = getattr(request.app.state, 'project_configs', {}).get(project_name)
    if entry:
        set_trace_attributes(
            project_uuid=str(entry.uuid),
            project_name=project_name,
            route_name=route_name_part or route_key,
            tags=list(get_current_request_tags()),
        )
    else:
        set_trace_attributes(
            route_name=route_name_part or route_key,
            tags=list(get_current_request_tags()),
        )


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
