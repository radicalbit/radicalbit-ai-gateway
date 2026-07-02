import asyncio
from collections.abc import Iterable
from contextvars import ContextVar
import logging
import re
from typing import Protocol

import httpx
from langchain_core.messages import BaseMessage
from traceloop.sdk.decorators import task, workflow

from radicalbit_ai_gateway.events.events_processor import emit_event
from opentelemetry import trace
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.metrics.define_metrics import guardrails_triggered_counter
from radicalbit_ai_gateway.models.event_payload import GuardrailEventPayload
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.gateway_config import get_model_from_model_id
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.guardrails import (
    CheckParameter,
    Guardrail,
    GuardrailBehaviorType,
    GuardrailClass,
    GuardrailParameter,
    GuardrailsAIParameter,
    GuardrailType,
    GuardrailWhereType,
    JudgeParameter,
    RedactParameter,
)
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.models.soft_block_info import SoftBlockInfo
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.content_utils import ContentUtils
from radicalbit_ai_gateway.utils.exceptions import GuardrailBadRequest

app_config = get_app_config()
logging_config_dict = app_config.log_config.model_dump()
logger = logging.getLogger(app_config.log_config.logger_name)


def _trunc(s: str, max_len: int = 120) -> str:
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + '...'


def _context_words(
    text: str,
    *,
    span: tuple[int, int],
    before: int = 3,
    after: int = 3,
    max_len: int = 200,
) -> str | None:
    """Return a short context snippet around span using whole-word windows."""
    if not text:
        return None
    start, end = span
    if start < 0 or end < 0 or end <= start:
        return None

    # Build (start,end,word) list.
    words = [(m.start(), m.end(), m.group(0)) for m in re.finditer(r'\S+', text)]
    if not words:
        return None

    # Find word indices that overlap the match span.
    hit = [i for i, (ws, we, _) in enumerate(words) if we > start and ws < end]
    if not hit:
        return None
    lo = max(0, min(hit) - before)
    hi = min(len(words) - 1, max(hit) + after)

    parts: list[str] = []
    for i in range(lo, hi + 1):
        w = words[i][2]
        if i in hit:
            parts.append(f'<<{w}>>')
        else:
            parts.append(w)

    snippet = ' '.join(parts).replace('\n', ' ').strip()
    if lo > 0:
        snippet = '… ' + snippet
    if hi < len(words) - 1:
        snippet = snippet + ' …'
    return _trunc(snippet, max_len=max_len)


class GuardrailCheckFunction(Protocol):
    async def __call__(
        self,
        messages: list[BaseMessage],
        params: GuardrailParameter,
        route_config: GatewayRouteConfig,
        **kwargs,
    ) -> bool: ...


def _iter_texts(messages: Iterable[BaseMessage]) -> Iterable[str]:
    """Yield plain text for each message.content."""
    for m in messages:
        yield ContentUtils.extract_text_content(getattr(m, 'content', ''))


def _texts_from_messages(messages: list[BaseMessage]) -> list[str]:
    """Return a list of non-empty strings extracted from messages (never lists)."""
    texts = [
        ContentUtils.extract_text_content(getattr(m, 'content', '')) for m in messages
    ]
    return [t for t in texts if isinstance(t, str) and t]


def _blob_from_messages(messages: list[BaseMessage]) -> str:
    """Build a single text blob from messages (safe for spaCy/Presidio)."""
    texts = _texts_from_messages(messages)
    return '\n'.join(texts) if texts else ''


class GuardrailCheck:
    def __init__(
        self,
        presidio_engine: PresidioEngine,
        judge_engine: JudgeEngine,
        cost_service: CostService,
        guardrails_by_name: dict[str, Guardrail] | None = None,
        chat_models_by_id: dict[str, Model] | None = None,
    ):
        self._presidio_engine = presidio_engine
        self._judge_engine = judge_engine
        self._guardrails_by_name = guardrails_by_name or {}
        self._chat_models_by_id = chat_models_by_id or {}
        self._cost_service = cost_service
        self._reason_payload_ctx: ContextVar[dict | None] = ContextVar(
            'guardrail_reason_payload', default=None
        )

        self._guardrail_check_mapping: dict[GuardrailType, GuardrailCheckFunction] = {
            GuardrailType.STARTS_WITH: self._check_starts_with,
            GuardrailType.ENDS_WITH: self._check_ends_with,
            GuardrailType.CONTAINS: self._check_contains,
            GuardrailType.REGEX: self._check_regex,
            GuardrailType.PRESIDIO_ANALYZER: self._check_presidio_analyzer,
            GuardrailType.JUDGE: self._check_judge,
            GuardrailType.GUARDRAILS_AI: self._check_guardrails_ai,
        }

    @staticmethod
    @task(name='check_starts_with')
    async def _check_starts_with(
        messages: list[BaseMessage],
        params: CheckParameter,
        route_config: GatewayRouteConfig,
        **kwargs,
    ) -> bool:
        """Check if any message text starts with a given value."""
        logger.debug(
            'Applying Guardrail %s on route %s',
            GuardrailType.STARTS_WITH,
            route_config.route_name,
        )
        values = params.values
        if not values:
            return False
        for text in _iter_texts(messages):
            for p in values:
                if text.startswith(p):
                    return True
        return False

    @staticmethod
    @task(name='check_ends_with')
    async def _check_ends_with(
        messages: list[BaseMessage],
        params: CheckParameter,
        route_config: GatewayRouteConfig,
        **kwargs,
    ) -> bool:
        """Check if any message text ends with a given value."""
        logger.debug(
            'Applying Guardrail %s on route %s',
            GuardrailType.ENDS_WITH,
            route_config.route_name,
        )
        values = params.values
        if not values:
            return False
        for text in _iter_texts(messages):
            for p in values:
                if text.endswith(p):
                    return True
        return False

    @staticmethod
    @task(name='check_contains')
    async def _check_contains(
        messages: list[BaseMessage],
        params: CheckParameter,
        route_config: GatewayRouteConfig,
        **kwargs,
    ) -> bool:
        """Check if any message text contains a given value."""
        logger.debug(
            'Applying Guardrail %s on route %s',
            GuardrailType.CONTAINS,
            route_config.route_name,
        )
        values = params.values
        if not values:
            return False
        for text in _iter_texts(messages):
            for p in values:
                if p.lower() in text.lower():
                    return True
        return False

    @staticmethod
    @task(name='check_regex')
    async def _check_regex(
        messages: list[BaseMessage],
        params: CheckParameter,
        route_config: GatewayRouteConfig,
        **kwargs,
    ) -> bool:
        """Check message text against regex patterns (case-insensitive by default)."""

        def _safe_compile_pattern(raw: str, flags: int, idx: int) -> re.Pattern | None:
            try:
                return re.compile(raw, flags)
            except re.error as e:
                logger.warning(
                    'REGEX guardrail: invalid pattern[%d]=%r (%s)', idx, raw, e
                )
                return None

        logger.debug(
            'Applying Guardrail %s on route %s',
            GuardrailType.REGEX,
            route_config.route_name,
        )

        patterns = params.values
        ignore_case = params.ignore_case
        flags = re.IGNORECASE if ignore_case else 0

        compiled = []
        for i, raw in enumerate(patterns):
            pat = _safe_compile_pattern(raw, flags, i)
            if pat is not None:
                compiled.append(pat)

        if not compiled:
            return False

        texts = _texts_from_messages(messages)
        if not texts:
            return False

        for mi, text in enumerate(texts):
            for pat in compiled:
                m = pat.search(text)
                if m:
                    logger.debug(
                        'REGEX guardrail: match on message[%d] with pattern %r at %s',
                        mi,
                        pat.pattern,
                        m.span(),
                    )
                    return True
        return False

    @task(name='presidio_analyzer')
    async def _check_presidio_analyzer(
        self,
        messages: list[BaseMessage],
        params: RedactParameter,
        route_config: GatewayRouteConfig,
        **kwargs,
    ) -> bool:
        """Run Presidio Analyzer over a single text blob (never a list)."""
        logger.debug(
            'Applying Guardrail %s on route %s',
            GuardrailType.PRESIDIO_ANALYZER,
            route_config.route_name,
        )

        language = params.language
        entities = params.entities

        # Build one safe string for spaCy (prevents E1041).
        blob = _blob_from_messages(messages)

        if not blob:
            return False

        try:
            analyzer = self._presidio_engine.get_analyzer(params.backend, params.ahds)
            # Run presidio analysis in thread pool to avoid blocking
            results = await asyncio.to_thread(
                analyzer.analyze,
                text=blob,
                entities=entities,
                language=language,
            )
        except Exception as e:
            logger.warning(
                'Presidio analyze failed on type=%s: %s', type(blob).__name__, e
            )
            return False
        if results:
            first_res = results[0]
            val = blob[first_res.start : first_res.end]
            reason = {
                'kind': 'presidio',
                'entity_type': first_res.entity_type,
                'value': val,
                'message_index': 0,
                'context': _context_words(blob, span=(first_res.start, first_res.end)),
            }
            self._reason_payload_ctx.set(reason)

            try:
                span = trace.get_current_span()
                if span.is_recording():
                    span.set_attribute('guardrail.presidio.matched_value', val)
                    span.set_attribute(
                        'guardrail.presidio.entity_type', first_res.entity_type
                    )
            except Exception:
                pass

            return True

        return False

    @task(name='check_judge')
    async def _check_judge(
        self,
        messages: list[BaseMessage],
        params: JudgeParameter,
        route_config: GatewayRouteConfig,
        **kwargs,
    ) -> bool:
        """Check using an LLM contextual judge (security, policy, etc.)."""
        try:
            primary_model = get_model_from_model_id(
                models_by_id=self._chat_models_by_id,
                route_name=route_config.route_name,
                model_id=params.model_id,
            )
            fallback_model = (
                get_model_from_model_id(
                    models_by_id=self._chat_models_by_id,
                    route_name=route_config.route_name,
                    model_id=params.fallback_model_id,
                )
                if params.fallback_model_id
                else None
            )

            logger.debug(
                'Running LLM-based guardrail on route=%s with model=%s',
                route_config.route_name,
                primary_model.model,
            )

            result = await self._judge_engine.execute_judge(
                messages=messages,
                judge_parameter=params,
                primary_model=primary_model,
                fallback_model=fallback_model,
                cost_service=self._cost_service,
                **kwargs,
            )

            logger.info(
                'Judge result: triggered=%s, reasoning=%s, violation_type=%s',
                result.triggered,
                result.reasoning,
                result.violation_type,
            )
        except Exception as e:
            logger.error('Judge communication error: %s', e)
            raise
        else:
            if result.triggered:
                # Capture structured reason payload for logs/response.
                texts = _texts_from_messages(messages)
                last_text = texts[-1] if texts else ''
                mi = max(0, len(texts) - 1)
                phase = kwargs.get('where')
                self._reason_payload_ctx.set(
                    {
                        'kind': 'judge',
                        # Align with other guardrails: value/message_index/context
                        'value': getattr(result, 'violation_type', None),
                        'message_index': mi,
                        'context': _trunc(last_text, max_len=200),
                        'phase': getattr(phase, 'name', None),
                        # Extra fields (for logs), will be sanitized out from API responses
                        'prompt_ref': params.prompt_ref,
                        'model_id': params.model_id,
                        'fallback_model_id': params.fallback_model_id,
                        'reasoning': _trunc(
                            str(getattr(result, 'reasoning', '') or ''), max_len=400
                        ),
                    }
                )
            return result.triggered

    @task(name='check_guardrails_ai')
    async def _check_guardrails_ai(
        self,
        messages: list[BaseMessage],
        params: GuardrailsAIParameter,
        route_config: GatewayRouteConfig,
        **kwargs,
    ) -> bool:
        """Check using external guardrails-ai validation service."""
        logger.debug(
            'Applying Guardrail %s on route %s',
            GuardrailType.GUARDRAILS_AI,
            route_config.route_name,
        )
        blob = _blob_from_messages(messages)
        if not blob:
            return False

        base = params.base_url.rstrip('/')
        try:
            async with httpx.AsyncClient(timeout=params.timeout) as client:
                # Resolve guard name to id
                guards_resp = await client.get(f'{base}/guards')
                guards_resp.raise_for_status()
                guard_id = None
                for g in guards_resp.json():
                    if g.get('name') == params.guard_name:
                        guard_id = g.get('id')
                        break
                resp = await client.post(
                    f'{base}/guards/{guard_id}/validate',
                    json={'llm_output': blob},
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException:
            logger.error(
                'Guardrails-AI timeout for guard=%s on route=%s',
                params.guard_name,
                route_config.route_name,
            )
            raise
        except httpx.HTTPStatusError as e:
            logger.error(
                'Guardrails-AI HTTP error %s for guard=%s: %s',
                e.response.status_code,
                params.guard_name,
                e,
            )
            raise
        except Exception as e:
            logger.error('Guardrails-AI communication error: %s', e)
            raise

        validation_passed = data.get('validationPassed', True)
        triggered = not validation_passed

        if triggered:
            texts = _texts_from_messages(messages)
            last_text = texts[-1] if texts else ''
            mi = max(0, len(texts) - 1)
            phase = kwargs.get('where')
            self._reason_payload_ctx.set(
                {
                    'kind': 'guardrails_ai',
                    'value': params.guard_name,
                    'message_index': mi,
                    'context': _trunc(last_text, max_len=200),
                    'phase': getattr(phase, 'name', None),
                    'guard_name': params.guard_name,
                }
            )
        return triggered

    @workflow(name='apply_check_guardrails')
    async def apply_guardrails(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        route_config: GatewayRouteConfig,
        messages: list[BaseMessage],
        where: GuardrailWhereType,
        project_uuid: str = '',
        project_name: str = '',
    ) -> SoftBlockInfo | None:
        """Apply guardrails to messages and return SoftBlockInfo on SOFT_BLOCK."""
        kwargs = {
            'request_uuid': request_uuid,
            'api_key_uuid': api_key_uuid,
            'group_uuid': group_uuid,
            'api_key_name': api_key_name,
            'group_name': group_name,
            'project_uuid': project_uuid,
            'project_name': project_name,
            'route_name': route_config.route_name,
            'where': where,
        }

        check_guardrails = self._get_guardrails_for_route(
            route_config=route_config,
            where=where,
            guardrail_class=GuardrailClass.CHECK,
            only_warn=False,
        )

        if not check_guardrails:
            return None

        for guardrail in check_guardrails:
            logger.debug(
                'Evaluating guardrail: %s (type=%s, where=%s, behavior=%s)',
                guardrail.name,
                guardrail.type.name,
                guardrail.where.name,
                guardrail.behavior.name,
            )

            check_function = self._guardrail_check_mapping.get(guardrail.type)
            if not check_function:
                raise GuardrailBadRequest(
                    f'Unknown guardrail type: {guardrail.type}', guardrail
                )

            try:
                token = self._reason_payload_ctx.set(None)
                is_triggered = await check_function(
                    messages,
                    guardrail.parameters,
                    route_config,
                    **kwargs,
                )
            except Exception as e:
                logger.error('Error applying guardrail %s: %s', guardrail.name, e)
                raise
            finally:
                reason_override = self._reason_payload_ctx.get()
                self._reason_payload_ctx.reset(token)

            if not is_triggered:
                continue
            should_stop, soft_block = self._handle_triggered_check_guardrail(
                guardrail=guardrail,
                where=where,
                route_name=route_config.route_name,
                request_uuid=request_uuid,
                api_key_uuid=api_key_uuid,
                group_uuid=group_uuid,
                api_key_name=api_key_name,
                group_name=group_name,
                project_uuid=project_uuid,
                project_name=project_name,
                messages=messages,
                reason_payload_override=reason_override,
            )
            if soft_block is not None:
                return soft_block
            if should_stop:
                return None
            # WARN/INFO: keep evaluating remaining guardrails
            continue

        return None

    def _find_first_check_match(
        self, guardrail: Guardrail, messages: list[BaseMessage]
    ) -> tuple[dict, str] | None:
        """Return (match_info, text) for the first matching CHECK guardrail.

        match_info always contains:
        - kind: starts_with | ends_with | contains | regex
        - message_index: int
        - span: (start, end) int tuple in the selected message text
        and one of:
        - value: str (for starts_with/ends_with/contains)
        - pattern: str (for regex)
        """
        if not isinstance(guardrail.parameters, CheckParameter):
            return None

        values = guardrail.parameters.values or []
        if not values:
            return None

        texts = _texts_from_messages(messages)
        if not texts:
            return None

        if guardrail.type == GuardrailType.STARTS_WITH:
            for mi, text in enumerate(texts):
                for v in values:
                    if text.startswith(v):
                        return (
                            {
                                'kind': 'starts_with',
                                'value': v,
                                'message_index': mi,
                                'span': (0, len(v)),
                            },
                            text,
                        )
            return None

        if guardrail.type == GuardrailType.ENDS_WITH:
            for mi, text in enumerate(texts):
                for v in values:
                    if text.endswith(v):
                        start = max(0, len(text) - len(v))
                        return (
                            {
                                'kind': 'ends_with',
                                'value': v,
                                'message_index': mi,
                                'span': (start, len(text)),
                            },
                            text,
                        )
            return None

        if guardrail.type == GuardrailType.CONTAINS:
            for mi, text in enumerate(texts):
                tl = text.lower()
                for v in values:
                    idx = tl.find(v.lower())
                    if idx != -1:
                        return (
                            {
                                'kind': 'contains',
                                'value': v,
                                'message_index': mi,
                                'span': (idx, idx + len(v)),
                            },
                            text,
                        )
            return None

        if guardrail.type == GuardrailType.REGEX:
            flags = re.IGNORECASE if guardrail.parameters.ignore_case else 0
            for mi, text in enumerate(texts):
                for raw in values:
                    try:
                        pat = re.compile(raw, flags)
                    except re.error:
                        continue
                    m = pat.search(text)
                    if m:
                        return (
                            {
                                'kind': 'regex',
                                'pattern': raw,
                                'message_index': mi,
                                'span': m.span(),
                            },
                            text,
                        )
            return None

        return None

    def _build_check_guardrail_reason_payload(
        self, guardrail: Guardrail, messages: list[BaseMessage]
    ) -> dict | None:
        """Build a structured reason payload to expose to clients in error.param.reason."""
        # For JUDGE and GUARDRAILS_AI, the payload is produced by the check function and passed via `reason_payload_override`.
        if guardrail.type in (
            GuardrailType.JUDGE,
            GuardrailType.GUARDRAILS_AI,
        ) or isinstance(guardrail.parameters, JudgeParameter | GuardrailsAIParameter):
            return None
        found = self._find_first_check_match(guardrail, messages)
        if not found:
            return None
        match, text = found
        ctx = _context_words(text, span=match['span'])
        payload: dict = {k: v for k, v in match.items() if k != 'span'}
        payload['context'] = ctx
        return payload

    @staticmethod
    def _format_check_reason_for_logs(reason_payload: dict | None) -> str | None:
        """Return a readable reason string for logs from a reason payload."""
        if not isinstance(reason_payload, dict):
            return None
        kind = reason_payload.get('kind')
        mi = reason_payload.get('message_index')
        if kind == 'presidio':
            et = reason_payload.get('entity_type')
            val = reason_payload.get('value')
            if et is not None and val is not None:
                s = f'presidio entity_type={_trunc(repr(et))} value={_trunc(repr(val))}'
            else:
                return None
            excerpt = reason_payload.get('context')
            if isinstance(excerpt, str) and excerpt:
                s += f' context="{_trunc(excerpt, max_len=120)}"'
            return s
        if kind in ('starts_with', 'ends_with', 'contains'):
            val = reason_payload.get('value')
            if kind and val is not None and mi is not None:
                s = f'{kind} value={_trunc(repr(val))} message_index={mi}'
            else:
                return None
        elif kind == 'regex':
            pat = reason_payload.get('pattern')
            if pat is not None and mi is not None:
                s = f'regex pattern={_trunc(repr(pat))} message_index={mi}'
            else:
                return None
        elif kind == 'judge':
            vt = reason_payload.get('value')
            pr = reason_payload.get('prompt_ref')
            mid = reason_payload.get('model_id')
            ph = reason_payload.get('phase')
            s = 'judge'
            if vt:
                s += f' value={_trunc(repr(vt), max_len=120)}'
            if pr:
                s += f' prompt_ref={_trunc(repr(pr), max_len=120)}'
            if mid:
                s += f' model_id={_trunc(repr(mid), max_len=120)}'
            if ph:
                s += f' phase={_trunc(repr(ph), max_len=40)}'
            reasoning = reason_payload.get('reasoning')
            if isinstance(reasoning, str) and reasoning:
                s += f' reasoning={_trunc(repr(reasoning), max_len=200)}'
            excerpt = reason_payload.get('context')
            if isinstance(excerpt, str) and excerpt:
                s += f' text="{_trunc(excerpt, max_len=120)}"'
            return s
        elif kind == 'guardrails_ai':
            gn = reason_payload.get('guard_name')
            ph = reason_payload.get('phase')
            s = 'guardrails_ai'
            if gn:
                s += f' guard_name={_trunc(repr(gn), max_len=120)}'
            if ph:
                s += f' phase={_trunc(repr(ph), max_len=40)}'
            excerpt = reason_payload.get('context')
            if isinstance(excerpt, str) and excerpt:
                s += f' text="{_trunc(excerpt, max_len=120)}"'
            return s
        else:
            return None

        ctx = reason_payload.get('context')
        if isinstance(ctx, str) and ctx:
            s += f' context="{ctx}"'
        return s

    def _handle_triggered_check_guardrail(
        self,
        *,
        guardrail: Guardrail,
        where: GuardrailWhereType,
        route_name: str,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        project_uuid: str = '',
        project_name: str = '',
        messages: list[BaseMessage],
        reason_payload_override: dict | None = None,
    ) -> tuple[bool, SoftBlockInfo | None]:
        attrs = {
            'name': guardrail.name,
            'type': guardrail.type.name,
            'where': where.name,
            'parameters': str(guardrail.parameters),
            'behavior': guardrail.behavior.name,
            'is_judge': guardrail.type == GuardrailType.JUDGE,
        }
        emit_event(
            GuardrailEventPayload(
                request_uuid=request_uuid,
                api_key_uuid=api_key_uuid,
                group_uuid=group_uuid,
                api_key_name=api_key_name,
                route_name=route_name,
                value=1.0,
                event_type=EventType.GUARDRAIL,
                group_name=group_name,
                project_uuid=project_uuid,
                project_name=project_name,
                name=guardrail.name,
                type=guardrail.type.name,
                where=where.name,
                parameters=str(guardrail.parameters),
                behavior=guardrail.behavior.name,
                is_judge=guardrail.type == GuardrailType.JUDGE,
            )
        )
        guardrails_triggered_counter.add(1, {'route_name': route_name, **attrs})

        # Expose structured details via GuardrailBadRequest.reason (surfaced in error.param.reason),
        # and also append a readable reason to logs for easier debugging.
        reason_payload = (
            reason_payload_override
            if isinstance(reason_payload_override, dict) and reason_payload_override
            else self._build_check_guardrail_reason_payload(guardrail, messages)
        )
        reason = self._format_check_reason_for_logs(reason_payload)
        log_message = (
            f'[GUARDRAIL TRIGGERED] [route={route_name}] '
            f'[name={guardrail.name}] [type={guardrail.type.name}] '
            f'[where={where.name}] [behavior={guardrail.behavior.name}]'
            + (f' [reason={reason}]' if reason else '')
        )

        client_message = (
            guardrail.response_message or f"Guardrail '{guardrail.name}' triggered"
        )

        if guardrail.behavior == GuardrailBehaviorType.BLOCK:
            raise GuardrailBadRequest(
                client_message,
                guardrail=guardrail,
                log_message=log_message,
                reason=reason_payload,
            )
        if guardrail.behavior == GuardrailBehaviorType.SOFT_BLOCK:
            logger.warning(log_message)
            return True, SoftBlockInfo(
                guardrail=guardrail, where=where, message=client_message
            )
        if guardrail.behavior == GuardrailBehaviorType.WARN:
            logger.warning(log_message)
        else:
            logger.info(log_message)
        return False, None

    async def evaluate_warn_triggered(
        self,
        route_config: GatewayRouteConfig,
        messages: list[BaseMessage],
        where: GuardrailWhereType,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
    ) -> bool:
        """Evaluate only WARN-behavior guardrails without emitting events/logs.
        Used to surface a response header for non-blocking guardrails.
        """

        check_guardrails = self._get_guardrails_for_route(
            route_config=route_config,
            where=where,
            guardrail_class=GuardrailClass.CHECK,
            only_warn=True,
        )

        if not check_guardrails:
            return False

        kwargs = {
            'request_uuid': request_uuid,
            'api_key_uuid': api_key_uuid,
            'group_uuid': group_uuid,
            'api_key_name': api_key_name,
            'group_name': group_name,
            'route_name': route_config.route_name,
            'where': where,
        }

        for guardrail in check_guardrails:
            check_function = self._guardrail_check_mapping.get(guardrail.type)
            if not check_function:
                continue
            try:
                if await check_function(
                    messages, guardrail.parameters, route_config, **kwargs
                ):
                    return True
            except Exception:
                # Ignore evaluation failures for WARN header calculation
                continue
        return False

    def _get_guardrails_for_route(
        self,
        route_config: GatewayRouteConfig,
        where: GuardrailWhereType,
        guardrail_class: GuardrailClass,
        only_warn: bool = False,
    ) -> list[Guardrail]:
        guardrail_names = route_config.guardrails or []
        guardrails: list[Guardrail] = []

        for gr_name in guardrail_names:
            guardrail = self._guardrails_by_name.get(gr_name)
            if not guardrail:
                logger.warning(
                    'Guardrail id %r not found for route %s',
                    gr_name,
                    route_config.route_name,
                )
                continue
            if not guardrail.enabled:
                continue
            if guardrail.guardrail_class() != guardrail_class:
                continue
            if guardrail.where not in (where, GuardrailWhereType.IO):
                continue
            if only_warn and guardrail.behavior != GuardrailBehaviorType.WARN:
                continue
            guardrails.append(guardrail)

        return guardrails
