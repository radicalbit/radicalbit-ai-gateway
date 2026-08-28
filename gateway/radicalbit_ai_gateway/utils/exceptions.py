import logging
from typing import Any

from fastapi import status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic.alias_generators import to_snake
from starlette.requests import Request

from radicalbit_ai_gateway.middleware.request_event_context import RequestEventContext
from radicalbit_ai_gateway.utils.app_config import get_app_config

app_config = get_app_config()
logging_config_dict = app_config.log_config.model_dump()
logger = logging.getLogger(app_config.log_config.logger_name)


class ErrorOut:
    """Standard OpenAI error response format.

    Fields:
    - error: Root object for all error info.
        - message: Human-readable description of the error.
        - type: Machine-readable error identifier (e.g. "guardrail_error", "token_limit_error", etc...).
        - code: Optional error code, may be null.
        - param: Parameter that caused the issue, if any.

    This format matches OpenAI's official tools and SDKs.
    If 'error.message' is missing, clients may not handle errors correctly.
    """

    def __init__(self, message, type_, code=None, param=None):
        self.error = {
            'message': message,
            'type': type_,
            'param': param,
            'code': code,
        }


class AppError(Exception):
    """Base class for all gateway exceptions with dual messages.
    - client_message: safe/UX-friendly text returned to the client.
    - log_message: technical/diagnostic text for logs (defaults to client_message).
    Carries HTTP status_code and optional code/param for structured responses.
    """

    def __init__(
        self,
        *,
        client_message: str,
        status_code: int,
        log_message: str | None = None,
        code: str | int | None = None,
        param: Any = None,
    ):
        self.client_message = client_message
        self.log_message = log_message or client_message
        self.status_code = status_code
        self.code = code
        self.param = param
        super().__init__(self.log_message)


def set_request_error_info(request: Request, error: AppError) -> None:
    """Set error info in the request context for exception handlers."""
    ctx = RequestEventContext.get_or_create(request)
    ctx.error_type = type(error).__name__
    ctx.error_code = str(error.code) if error.code else None


class GatewayError(AppError):
    def __init__(
        self,
        message: str,
        status_code: int,
        *,
        log_message: str | None = None,
        code: Any = None,
        param: Any = None,
    ):
        super().__init__(
            client_message=message,
            status_code=status_code,
            log_message=log_message,
            code=code,
            param=param,
        )


class GatewayInternalError(GatewayError):
    def __init__(self, message: str, *, log_message: str | None = None):
        super().__init__(
            message,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            log_message=log_message,
            code='gateway_internal_error',
        )


class GatewayBadRequest(GatewayError):
    def __init__(self, message: str, *, log_message: str | None = None):
        super().__init__(
            message,
            status.HTTP_400_BAD_REQUEST,
            log_message=log_message,
            code='gateway_bad_request',
        )


class GatewayNotFoundError(GatewayError):
    def __init__(self, message: str, *, log_message: str | None = None):
        super().__init__(
            message,
            status.HTTP_404_NOT_FOUND,
            log_message=log_message,
            code='gateway_not_found',
        )


class TagsHeaderError(GatewayError):
    """Invalid ``X-RB-Tags`` header."""

    def __init__(self, message: str, code: str, *, log_message: str | None = None):
        super().__init__(
            message,
            status.HTTP_400_BAD_REQUEST,
            log_message=log_message,
            code=code,
        )


class ApiKeyError(AppError):
    def __init__(self, message: str, code: str, *, log_message: str | None = None):
        super().__init__(
            client_message=message,
            status_code=status.HTTP_401_UNAUTHORIZED,
            log_message=log_message,
            code=code,
        )


class MissingApiKey(ApiKeyError):
    def __init__(self, message: str, *, log_message: str | None = None):
        super().__init__(message, 'key_missing_unauthorized', log_message=log_message)


class InvalidApiKey(ApiKeyError):
    def __init__(self, message: str, *, log_message: str | None = None):
        super().__init__(message, 'key_invalid_unauthorized', log_message=log_message)


class InvalidJwtToken(ApiKeyError):
    def __init__(self, message: str, *, log_message: str | None = None):
        super().__init__(message, 'invalid_jwt_token', log_message=log_message)


class McpTransportError(AppError):
    """HTTP-level failure on the inbound MCP endpoint.

    Covers transport concerns only (bad Origin, unknown project/route,
    unsupported protocol version, key not bound to the route). Protocol-level
    failures are JSON-RPC ``error`` bodies over HTTP 200 instead — see
    ``mcp_proxy/jsonrpc.py``.
    """

    def __init__(
        self,
        message: str,
        status_code: int,
        *,
        code: str | None = None,
        log_message: str | None = None,
    ):
        super().__init__(
            client_message=message,
            status_code=status_code,
            code=code,
            log_message=log_message,
        )


class GuardrailError(AppError):
    def __init__(
        self,
        message: str,
        status_code: int,
        guardrail: Any,
        *,
        log_message: str | None = None,
        code: Any = None,
        reason: dict | None = None,
    ):
        super().__init__(
            client_message=message,
            status_code=status_code,
            log_message=log_message,
            code=code,
            param=guardrail,
        )
        self.guardrail = guardrail
        self.reason = reason


class GuardrailBadRequest(GuardrailError):
    def __init__(
        self,
        message: str,
        guardrail: Any,
        *,
        log_message: str | None = None,
        reason: dict | None = None,
    ):
        super().__init__(
            message,
            status.HTTP_400_BAD_REQUEST,
            guardrail,
            log_message=log_message,
            reason=reason,
            code='guardrail_violation_bad_request',
        )


# -----------------------------------------------------------------------------
# Judge-specific exceptions
# -----------------------------------------------------------------------------


class JudgeInternalError(AppError):
    """Base exception for judge-related errors."""

    def __init__(
        self,
        message: str,
        *,
        log_message: str | None = None,
        model_id: str | None = None,
    ):
        self.model_id = model_id
        super().__init__(
            client_message=message,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            log_message=log_message,
            code='judge_internal_error',
        )


class JudgeOutputTruncatedError(JudgeInternalError):
    """Raised when judge output is truncated due to max_tokens limit."""

    def __init__(self, finish_reason: str, model_id: str):
        self.finish_reason = finish_reason
        message = (
            f"Judge output truncated (finish_reason='{finish_reason}'). "
            'Consider increasing max_tokens in judge configuration.'
        )
        log_message = (
            f"Judge output truncated: finish_reason='{finish_reason}', model='{model_id}'. "
            'The max_tokens limit was reached before the model could complete its response.'
        )
        super().__init__(message, log_message=log_message, model_id=model_id)
        self.code = 'judge_output_truncated_internal_error'


class JudgeParsingError(JudgeInternalError):
    """Raised when judge output cannot be parsed as valid JSON."""

    def __init__(
        self,
        raw_content: str | None,
        original_error: Exception,
        model_id: str | None = None,
    ):
        self.raw_content = raw_content
        self.original_error = original_error
        content_preview = (
            (raw_content[:100] + '...')
            if raw_content and len(raw_content) > 100
            else raw_content
        )
        message = 'Failed to parse judge output. The model did not return valid JSON.'
        log_message = (
            f'Failed to parse judge output as JSON. '
            f'Content: {content_preview!r}. Error: {original_error}'
        )
        super().__init__(message, log_message=log_message, model_id=model_id)
        self.code = 'judge_parsing_internal_error'


def judge_exception_handler(request: Request, err: JudgeInternalError):
    set_request_error_info(request, err)
    return _log_and_json_response(err, 'judge_internal_error')


def _guardrail_param_payload(guardrail: Any) -> Any:
    """Build a JSON-serializable payload to put into error.param for guardrail_error responses.
    We keep the original `err.guardrail` object intact (for internal code/tests), but expose
    a stable client-facing structure.
    """
    if guardrail is None:
        return None

    def _name(v: Any) -> Any:
        # Enum-like objects often have `.name`; otherwise keep the raw value.
        try:
            n = getattr(v, 'name', None)
        except Exception:
            return v
        else:
            return n if n is not None else v

    def _safe_str(v: Any) -> str:
        try:
            return str(v)
        except Exception:
            return f'<unprintable {type(v).__name__}>'

    fallback = {'class': type(guardrail).__name__, 'repr': _safe_str(guardrail)}
    _SENSITIVE_PARAM_KEYS = {'api_key', 'base_url', 'ahds'}

    def _serialize_params(params: Any) -> Any:
        if isinstance(params, dict):
            return {k: v for k, v in params.items() if k not in _SENSITIVE_PARAM_KEYS}
        if isinstance(params, list):
            return params
        if hasattr(params, 'model_dump'):
            try:
                dumped = params.model_dump(exclude_none=True)
            except Exception:
                return _safe_str(params)
            else:
                for k in _SENSITIVE_PARAM_KEYS:
                    dumped.pop(k, None)
                return dumped
        return _safe_str(params)

    payload: dict[str, Any] = {}
    try:
        for key, attr, transform in (
            ('name', 'name', None),
            ('type', 'type', _name),
            ('where', 'where', _name),
            ('behavior', 'behavior', _name),
            ('id', 'id', None),
        ):
            val = getattr(guardrail, attr, None)
            if val is None or val == '':
                continue
            payload[key] = transform(val) if transform else val

        params = getattr(guardrail, 'parameters', None)
        if params:
            payload['parameters'] = _serialize_params(params)
    except Exception:
        return fallback

    return payload or fallback


class TokenLimitExceeded(AppError):
    def __init__(self, message: str, code: str, *, log_message: str | None = None):
        super().__init__(
            client_message=message,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            log_message=log_message,
            code=code,
        )


class RBRateLimitExceeded(AppError):
    def __init__(
        self,
        message: str,
        code: str,
        *,
        log_message: str | None = None,
        param: Any = None,
    ):
        super().__init__(
            client_message=message,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            log_message=log_message,
            code=code,
            param=param,
        )


class RequestRateLimitExceeded(RBRateLimitExceeded):
    def __init__(
        self,
        message: str,
        *,
        log_message: str | None = None,
        route_name: str | None = None,
    ):
        super().__init__(
            message,
            'request_rate_limited',
            log_message=log_message,
            param=route_name,
        )


class AudioDurationLimitExceeded(RBRateLimitExceeded):
    def __init__(
        self,
        message: str,
        *,
        log_message: str | None = None,
        route_name: str | None = None,
    ):
        super().__init__(
            message,
            'audio_duration_rate_limited',
            log_message=log_message,
            param=route_name,
        )


class InputTokenLimitExceeded(TokenLimitExceeded):
    def __init__(self, message: str, *, log_message: str | None = None):
        super().__init__(message, 'token_limit_rate_limited', log_message=log_message)


class OutputTokenLimitExceeded(TokenLimitExceeded):
    def __init__(self, message: str, *, log_message: str | None = None):
        super().__init__(message, 'token_limit_rate_limited', log_message=log_message)


class ModelInvokerError(AppError):
    def __init__(
        self,
        message: str,
        status_code: int,
        *,
        log_message: str | None = None,
        code: str | None = None,
    ):
        super().__init__(
            client_message=message,
            status_code=status_code,
            log_message=log_message,
            code=code,
        )


class ModelInvokerInternalError(ModelInvokerError):
    def __init__(self, message: str, *, log_message: str | None = None):
        super().__init__(
            message,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            log_message=log_message,
            code='model_invoker_internal_error',
        )


class ModelInvokerBadRequest(ModelInvokerError):
    def __init__(self, message: str, *, log_message: str | None = None):
        super().__init__(
            message,
            status.HTTP_400_BAD_REQUEST,
            log_message=log_message,
            code='model_invoker_bad_request',
        )


class AuthRegistryError(AppError):
    def __init__(
        self,
        message: str,
        status_code: int,
        code: str,
        *,
        log_message: str | None = None,
    ):
        super().__init__(
            client_message=message,
            status_code=status_code,
            code=code,
            log_message=log_message,
        )


class KeyInternalError(AuthRegistryError):
    def __init__(self, message: str, *, log_message: str | None = None):
        super().__init__(
            message,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            'key_internal_error',
            log_message=log_message,
        )


class KeyNotFoundError(AuthRegistryError):
    def __init__(self, message: str, *, log_message: str | None = None):
        super().__init__(
            message,
            status.HTTP_404_NOT_FOUND,
            'key_not_found',
            log_message=log_message,
        )


class KeyAlreadyExistsError(AuthRegistryError):
    def __init__(self, message: str, *, log_message: str | None = None):
        super().__init__(
            message,
            status.HTTP_400_BAD_REQUEST,
            'key_already_exists_bad_request',
            log_message=log_message,
        )


class KeyOperationNotAllowedError(AuthRegistryError):
    def __init__(self, message: str, *, log_message: str | None = None):
        super().__init__(
            message,
            status.HTTP_405_METHOD_NOT_ALLOWED,
            'key_operation_method_not_allowed',
            log_message=log_message,
        )


class KeyGroupAlreadyExistsError(AuthRegistryError):
    def __init__(self, message: str, *, log_message: str | None = None):
        super().__init__(
            message,
            status.HTTP_400_BAD_REQUEST,
            'key_group_already_exists_bad_request',
            log_message=log_message,
        )


class GroupInternalError(AuthRegistryError):
    def __init__(self, message: str, *, log_message: str | None = None):
        super().__init__(
            message,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            'group_internal_error',
            log_message=log_message,
        )


class GroupNotFoundError(AuthRegistryError):
    def __init__(self, message: str, *, log_message: str | None = None):
        super().__init__(
            message,
            status.HTTP_404_NOT_FOUND,
            'group_not_found',
            log_message=log_message,
        )


class GroupAlreadyExistsError(AuthRegistryError):
    def __init__(self, message: str, *, log_message: str | None = None):
        super().__init__(
            message,
            status.HTTP_400_BAD_REQUEST,
            'group_already_exists_bad_request',
            log_message=log_message,
        )


class GroupOperationNotAllowedError(AuthRegistryError):
    def __init__(self, message: str, *, log_message: str | None = None):
        super().__init__(
            message,
            status.HTTP_405_METHOD_NOT_ALLOWED,
            'group_operation_method_not_allowed',
            log_message=log_message,
        )


class RouteNotFoundError(AuthRegistryError):
    def __init__(self, message: str, *, log_message: str | None = None):
        super().__init__(
            message,
            status.HTTP_404_NOT_FOUND,
            'route_not_found',
            log_message=log_message,
        )


class ProjectInternalError(AuthRegistryError):
    def __init__(self, message: str, *, log_message: str | None = None):
        super().__init__(
            message,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            'project_internal_error',
            log_message=log_message,
        )


class ProjectNotFoundError(AuthRegistryError):
    def __init__(self, message: str, *, log_message: str | None = None):
        super().__init__(
            message,
            status.HTTP_404_NOT_FOUND,
            'project_not_found',
            log_message=log_message,
        )


class ProjectAlreadyExistsError(AuthRegistryError):
    def __init__(self, message: str, *, log_message: str | None = None):
        super().__init__(
            message,
            status.HTTP_400_BAD_REQUEST,
            'project_already_exists_bad_request',
            log_message=log_message,
        )


class ProjectConfigValidationError(AuthRegistryError):
    def __init__(self, message: str, *, log_message: str | None = None):
        super().__init__(
            message,
            status.HTTP_400_BAD_REQUEST,
            'project_config_validation_error',
            log_message=log_message,
        )


class SecretNotFoundError(AppError):
    def __init__(self, key: str, source: str = ''):
        message = f"Secret '{key}' not found"
        if source:
            message += f' in {source}'
        super().__init__(
            client_message=message,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code='secret_not_found',
        )
        self.key = key
        self.source = source


class BudgetLimitExceeded(AppError):
    def __init__(self, message: str, code: str, *, log_message: str | None = None):
        super().__init__(
            client_message=message,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            log_message=log_message,
            code=code,
        )


class BudgetLimitExceededError(BudgetLimitExceeded):
    def __init__(self, message: str, *, log_message: str | None = None):
        super().__init__(message, 'budget_limit_rate_limited', log_message=log_message)


def _log_and_json_response(
    err: AppError, error_type: str, *, param_override: Any = None
) -> JSONResponse:
    level = logging.ERROR if err.status_code >= 500 else logging.WARNING
    logger.log(
        level,
        err.log_message,
        extra={
            'error_type': error_type,
            'status_code': err.status_code,
            'code': err.code,
            'param': param_override if param_override is not None else err.param,
        },
    )
    return JSONResponse(
        status_code=err.status_code,
        content=jsonable_encoder(
            {
                'error': ErrorOut(
                    err.client_message,
                    type_=error_type,
                    code=err.code if err.code is not None else err.status_code,
                    param=param_override if param_override is not None else err.param,
                ).error
            }
        ),
    )


def gateway_exception_handler(request: Request, err: GatewayError):
    set_request_error_info(request, err)
    return _log_and_json_response(err, 'gateway_error')


def guardrail_exception_handler(request: Request, err: GuardrailError):
    set_request_error_info(request, err)
    guardrail_obj = getattr(err, 'guardrail', None)
    payload = _guardrail_param_payload(guardrail_obj)
    reason = getattr(err, 'reason', None)
    if isinstance(payload, dict) and isinstance(reason, dict) and reason:
        # Never expose internal judge configuration in API responses.
        sanitized_reason = dict(reason)
        sanitized_reason.pop('prompt_ref', None)
        sanitized_reason.pop('model_id', None)
        sanitized_reason.pop('fallback_model_id', None)
        payload = {**payload, 'reason': sanitized_reason}
    response = _log_and_json_response(err, 'guardrail_error', param_override=payload)
    # Surface that a guardrail (hard block) was triggered
    response.headers['X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED'] = 'true'
    return response


def token_limiter_exception_handler(request: Request, err: TokenLimitExceeded):
    set_request_error_info(request, err)
    return _log_and_json_response(err, 'rate_limit_error')


def model_invoker_exception_handler(request: Request, err: ModelInvokerError):
    set_request_error_info(request, err)
    return _log_and_json_response(err, 'model_invoker_error')


def api_key_exception_handler(request: Request, err: ApiKeyError):
    set_request_error_info(request, err)
    return _log_and_json_response(err, 'authentication_error')


def auth_registry_exception_handler(request: Request, err: AuthRegistryError):
    set_request_error_info(request, err)
    return _log_and_json_response(err, 'auth_registry_error')


def mcp_transport_exception_handler(request: Request, err: McpTransportError):
    set_request_error_info(request, err)
    return _log_and_json_response(err, 'mcp_error')


class AlertRuleNotFoundError(AppError):
    def __init__(self, message: str = 'Alert rule not found'):
        super().__init__(
            client_message=message,
            status_code=status.HTTP_404_NOT_FOUND,
            code='alert_rule_not_found',
        )


class AlertRuleInvalidEventError(AppError):
    def __init__(self, message: str = 'Invalid event for route'):
        super().__init__(
            client_message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
            code='invalid_alert_rule_event',
        )


class AlertRuleUnsupportedTimeAggregationError(AppError):
    def __init__(
        self,
        message: str = 'Time aggregation "window" is not currently supported. Only "instant" is supported.',
    ):
        super().__init__(
            client_message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
            code='unsupported_time_aggregation',
        )


class AlertRuleInternalError(AppError):
    def __init__(self, message: str = 'Alert rule internal error'):
        super().__init__(
            client_message=message,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code='alert_rule_internal_error',
        )


def alert_rule_exception_handler(request: Request, err: AppError):
    set_request_error_info(request, err)
    return _log_and_json_response(err, 'alert_rule_error')


async def rate_limit_exceeded_handler(request: Request, exc: RequestRateLimitExceeded):
    set_request_error_info(request, exc)
    return _log_and_json_response(exc, 'rate_limit_error')


async def audio_duration_limit_exceeded_handler(
    request: Request, exc: AudioDurationLimitExceeded
):
    set_request_error_info(request, exc)
    return _log_and_json_response(exc, 'rate_limit_error')


def budget_limiter_exception_handler(request: Request, err: BudgetLimitExceeded):
    set_request_error_info(request, err)
    return _log_and_json_response(err, 'budget_limit_error')


async def unhandled_exception_handler(request: Request, err: Exception):
    """Catch-all handler for unhandled exceptions.

    Sets error_type to the exception class name and error_code to the snake_case of error_type
    so that unhandled errors are properly tracked in the request events
    Also sets is_unhandled_error flag so the status is correctly categorized.
    """
    ctx = RequestEventContext.get_or_create(request)
    ctx.error_type = type(err).__name__
    error_str = str(err)
    ctx.error_code = to_snake(ctx.error_type)
    ctx.is_unhandled_error = True

    logger.exception(
        'Unhandled exception: %s (error_type=%s, error_code=%s)',
        error_str,
        ctx.error_type,
        ctx.error_code,
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            'error': {
                'message': 'An internal error occurred. Please try again later.',
                'type': 'internal_error',
                'code': status.HTTP_500_INTERNAL_SERVER_ERROR,
            }
        },
    )
