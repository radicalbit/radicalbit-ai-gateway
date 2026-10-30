import asyncio
from contextvars import ContextVar
import logging
import re
from typing import NamedTuple, Protocol

import httpx
from opentelemetry import trace
from traceloop.sdk.decorators import task, workflow

from radicalbit_ai_gateway.events.events_processor import emit_event
from radicalbit_ai_gateway.guardrails.judges.decision_judge_engine import (
    DecisionJudgeEngine,
)
from radicalbit_ai_gateway.guardrails.judges.judge_engine import (
    JudgeEngine,
    JudgeUsageCounter,
)
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.llm.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from radicalbit_ai_gateway.metrics.define_metrics import guardrails_triggered_counter
from radicalbit_ai_gateway.models.event_payload import GuardrailEventPayload
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.gateway_config import get_model_from_model_id
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.guardrails import (
    CheckParameter,
    DecisionJudgeParameter,
    Guardrail,
    GuardrailBehaviorType,
    GuardrailClass,
    GuardrailHistory,
    GuardrailMessageRole,
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
from radicalbit_ai_gateway.utils.exceptions import (
    GuardrailBadRequest,
    JudgeInternalError,
)

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


# A check function sets this when it triggers. apply_guardrails reads it.
_reason_payload_ctx: ContextVar[dict | None] = ContextVar(
    'guardrail_reason_payload', default=None
)

_TYPE_TO_ROLE = {'human': 'user', 'ai': 'assistant', 'system': 'system', 'tool': 'tool'}


class _Text(NamedTuple):
    """The text of one message, with its position in the full message list."""

    index: int
    role: str
    text: str


def _indexed_texts(
    messages: list[BaseMessage], indices: list[int] | None = None
) -> list[_Text]:
    """One item per message that has text. Blank text does not count.

    ``indices`` gives the position of each message in the full list. Without
    it, the position in ``messages`` is used.
    """
    if indices is None:
        indices = list(range(len(messages)))
    items: list[_Text] = []
    for i, m in zip(indices, messages):
        text = ContentUtils.extract_text_content(getattr(m, 'content', ''))
        # A judge drops blank text too, so the reported indexes stay true.
        if isinstance(text, str) and text.strip():
            msg_type = getattr(m, 'type', '')
            items.append(_Text(i, _TYPE_TO_ROLE.get(msg_type, msg_type), text))
    return items


def _blob_with_spans(items: list[_Text]) -> tuple[str, list[tuple[int, int, _Text]]]:
    """Join the texts with newlines. Return the blob and the span of each text."""
    parts: list[str] = []
    spans: list[tuple[int, int, _Text]] = []
    pos = 0
    for it in items:
        if parts:
            pos += 1  # the newline
        spans.append((pos, pos + len(it.text), it))
        parts.append(it.text)
        pos += len(it.text)
    return '\n'.join(parts), spans


def _text_at_offset(
    spans: list[tuple[int, int, _Text]], offset: int
) -> tuple[int, _Text] | None:
    """Return (span start, text) of the text that holds the blob offset."""
    for start, end, it in spans:
        if start <= offset < end:
            return start, it
    return None


def _window_payload(items: list[_Text]) -> dict:
    """Index fields for a check that reads all texts as one (a judge).

    It cannot point at one message, so ``message_indices`` lists every message
    it read.
    """
    one = items[0] if len(items) == 1 else None
    return {
        'message_indices': [it.index for it in items],
        'role': one.role if one else None,
        'context': _trunc(items[-1].text, max_len=200) if items else '',
    }


def _judge_texts(messages: list[BaseMessage], kwargs: dict) -> list[_Text]:
    """Return the texts a judge reads. Mirrors utils.judge.content_extractor."""
    items = _indexed_texts(messages, kwargs.get('message_indices'))
    if kwargs.get('where') == GuardrailWhereType.OUTPUT:
        return [it for it in items if it.role == 'assistant'][-1:]
    if kwargs.get('message_roles') is None:
        return [it for it in items if it.role == 'user']
    return items


def _match_check(
    kind: GuardrailType, params: CheckParameter, items: list[_Text]
) -> dict | None:
    """Find the first text that matches. Return the reason payload or None."""
    values = params.values or []
    if not values:
        return None

    def payload(it: _Text, span: tuple[int, int], **extra) -> dict:
        return {
            'kind': kind.value.lower(),
            **extra,
            'message_indices': [it.index],
            'role': it.role,
            'context': _context_words(it.text, span=span),
        }

    if kind == GuardrailType.REGEX:
        flags = re.IGNORECASE if params.ignore_case else 0
        compiled: list[tuple[str, re.Pattern]] = []
        for i, raw in enumerate(values):
            try:
                compiled.append((raw, re.compile(raw, flags)))
            except re.error as e:
                logger.warning(
                    'REGEX guardrail: invalid pattern[%d]=%r (%s)', i, raw, e
                )
        for it in items:
            for raw, pat in compiled:
                m = pat.search(it.text)
                if m:
                    return payload(it, m.span(), pattern=raw)
        return None

    for it in items:
        text = it.text
        for v in values:
            if kind == GuardrailType.STARTS_WITH and text.startswith(v):
                return payload(it, (0, len(v)), value=v)
            if kind == GuardrailType.ENDS_WITH and text.endswith(v):
                return payload(it, (max(0, len(text) - len(v)), len(text)), value=v)
            if kind == GuardrailType.CONTAINS:
                idx = text.lower().find(v.lower())
                if idx != -1:
                    return payload(it, (idx, idx + len(v)), value=v)
    return None


def _run_check(
    kind: GuardrailType,
    messages: list[BaseMessage],
    params: CheckParameter,
    route_config: GatewayRouteConfig,
    kwargs: dict,
) -> bool:
    logger.debug('Applying Guardrail %s on route %s', kind, route_config.route_name)
    items = _indexed_texts(messages, kwargs.get('message_indices'))
    reason = _match_check(kind, params, items)
    if reason is None:
        return False
    logger.debug(
        '%s guardrail: match on message[%s]', kind, reason.get('message_indices')
    )
    _reason_payload_ctx.set(reason)
    return True


# ---------------------------------------------------------------------------
# Role-based message filtering
# ---------------------------------------------------------------------------

_ROLE_TO_TYPE: dict[GuardrailMessageRole, type[BaseMessage]] = {
    GuardrailMessageRole.USER: HumanMessage,
    GuardrailMessageRole.SYSTEM: SystemMessage,
    GuardrailMessageRole.TOOL: ToolMessage,
    GuardrailMessageRole.ASSISTANT: AIMessage,
}


def _filter_messages_by_roles(
    messages: list[BaseMessage],
    roles: list[GuardrailMessageRole] | None,
) -> list[BaseMessage]:
    """Return only the messages whose type matches the given roles.

    When *roles* is ``None`` (not configured) the function returns all messages
    unchanged — preserving the original gateway behavior where all messages in
    the list are scanned regardless of type.

    When *roles* is an explicit list (even empty) only messages whose type
    matches an entry in the list are returned.  An empty list returns nothing.
    """
    if roles is None:
        # Not configured: original behavior — no filtering.
        return messages
    if not roles:
        return []
    allowed = tuple(_ROLE_TO_TYPE[r] for r in roles if r in _ROLE_TO_TYPE)
    if not allowed:
        return []
    return [m for m in messages if isinstance(m, allowed)]


_JUDGE_TYPES = (GuardrailType.JUDGE, GuardrailType.DECISION_JUDGE)


def _window_roles(
    guardrail: Guardrail, where: GuardrailWhereType
) -> list[GuardrailMessageRole] | None:
    """Return the roles the window counts. A judge reads user messages by default."""
    if (
        guardrail.message_roles is None
        and guardrail.type in _JUDGE_TYPES
        and where != GuardrailWhereType.OUTPUT
    ):
        return [GuardrailMessageRole.USER]
    return guardrail.message_roles


def _select_messages(
    messages: list[BaseMessage],
    guardrail: Guardrail,
    where: GuardrailWhereType,
    *,
    windowed: bool = True,
    skip: int = 0,
) -> list[tuple[int, BaseMessage]]:
    """Keep the roles first. Then cut the window on what is left.

    ``skip`` drops the first messages: the system prompt the gateway adds is
    not part of the conversation. The window only applies on input, and only
    when ``windowed`` (a call with no conversation turns it off).

    Each item keeps its index in ``messages``, so a redacted copy can go back
    in its place.
    """
    indexed = list(enumerate(messages))[skip:]
    kept = _filter_messages_by_roles(
        [m for _, m in indexed], _window_roles(guardrail, where)
    )
    selected = [(i, m) for i, m in indexed if any(m is k for k in kept)]
    if not windowed or where == GuardrailWhereType.OUTPUT:
        return selected
    if guardrail.history == GuardrailHistory.LAST:
        return selected[-1:]
    if guardrail.history == GuardrailHistory.LAST_N:
        return selected[-(guardrail.last_n or 1) :]
    return selected


class GuardrailCheck:
    def __init__(
        self,
        presidio_engine: PresidioEngine,
        judge_engine: JudgeEngine,
        cost_service: CostService,
        guardrails_by_name: dict[str, Guardrail] | None = None,
        chat_models_by_id: dict[str, Model] | None = None,
        decision_judge_engine: DecisionJudgeEngine | None = None,
    ):
        self._presidio_engine = presidio_engine
        self._judge_engine = judge_engine
        self._decision_judge_engine = decision_judge_engine
        self._guardrails_by_name = guardrails_by_name or {}
        self._chat_models_by_id = chat_models_by_id or {}
        self._cost_service = cost_service
        self._reason_payload_ctx = _reason_payload_ctx

        self._guardrail_check_mapping: dict[GuardrailType, GuardrailCheckFunction] = {
            GuardrailType.STARTS_WITH: self._check_starts_with,
            GuardrailType.ENDS_WITH: self._check_ends_with,
            GuardrailType.CONTAINS: self._check_contains,
            GuardrailType.REGEX: self._check_regex,
            GuardrailType.PRESIDIO_ANALYZER: self._check_presidio_analyzer,
            GuardrailType.JUDGE: self._check_judge,
            GuardrailType.DECISION_JUDGE: self._check_decision_judge,
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
        return _run_check(
            GuardrailType.STARTS_WITH, messages, params, route_config, kwargs
        )

    @staticmethod
    @task(name='check_ends_with')
    async def _check_ends_with(
        messages: list[BaseMessage],
        params: CheckParameter,
        route_config: GatewayRouteConfig,
        **kwargs,
    ) -> bool:
        """Check if any message text ends with a given value."""
        return _run_check(
            GuardrailType.ENDS_WITH, messages, params, route_config, kwargs
        )

    @staticmethod
    @task(name='check_contains')
    async def _check_contains(
        messages: list[BaseMessage],
        params: CheckParameter,
        route_config: GatewayRouteConfig,
        **kwargs,
    ) -> bool:
        """Check if any message text contains a given value (ignores case)."""
        return _run_check(
            GuardrailType.CONTAINS, messages, params, route_config, kwargs
        )

    @staticmethod
    @task(name='check_regex')
    async def _check_regex(
        messages: list[BaseMessage],
        params: CheckParameter,
        route_config: GatewayRouteConfig,
        **kwargs,
    ) -> bool:
        """Check message text against regex patterns."""
        return _run_check(GuardrailType.REGEX, messages, params, route_config, kwargs)

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

        # One safe string for spaCy (prevents E1041). Spans map it back.
        items = _indexed_texts(messages, kwargs.get('message_indices'))
        blob, spans = _blob_with_spans(items)

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
            hit = _text_at_offset(spans, first_res.start)
            if hit:
                span_start, it = hit
                local = (first_res.start - span_start, first_res.end - span_start)
                where_found = {
                    'message_indices': [it.index],
                    'role': it.role,
                    'context': _context_words(it.text, span=local),
                }
            else:
                where_found = {'message_indices': [], 'role': None, 'context': None}
            reason = {
                'kind': 'presidio',
                'entity_type': first_res.entity_type,
                'value': val,
                **where_found,
            }
            _reason_payload_ctx.set(reason)

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
        count_judge_usage: JudgeUsageCounter | None = None,
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
                count_usage=count_judge_usage,
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
                phase = kwargs.get('where')
                _reason_payload_ctx.set(
                    {
                        'kind': 'judge',
                        'value': getattr(result, 'violation_type', None),
                        # The judge reads the texts as one: the index is
                        # exact only when it read one message.
                        **_window_payload(_judge_texts(messages, kwargs)),
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

                try:
                    span = kwargs.get('parent_span') or trace.get_current_span()
                    span_context = span.get_span_context() if span else None
                    logger.info(
                        'CHECK_JUDGE TELEMETRY: span_id=%s, name=%s, is_recording=%s',
                        hex(span_context.span_id) if span_context else None,
                        getattr(span, 'name', None),
                        span.is_recording() if span else False,
                    )
                    if span and span.is_recording():
                        span.set_attribute(
                            'guardrail.judge.violation_type',
                            getattr(result, 'violation_type', '') or '',
                        )
                        span.set_attribute(
                            'guardrail.judge.reasoning',
                            getattr(result, 'reasoning', '') or '',
                        )
                        span.set_attribute(
                            'guardrail.judge.prompt_ref',
                            params.prompt_ref or '',
                        )
                        span.set_attribute(
                            'guardrail.judge.model_id',
                            params.model_id or '',
                        )
                except Exception as telemetry_err:
                    logger.error('CHECK_JUDGE TELEMETRY ERROR: %s', telemetry_err)
            return result.triggered

    @task(name='check_decision_judge')
    async def _check_decision_judge(
        self,
        messages: list[BaseMessage],
        params: DecisionJudgeParameter,
        route_config: GatewayRouteConfig,
        **kwargs,
    ) -> bool:
        """Ask a decision model one yes/no question: trigger when noul >= threshold."""
        if self._decision_judge_engine is None:
            raise JudgeInternalError(
                'Decision judge failed',
                log_message='No decision judge engine is configured',
                model_id=params.model_id,
            )
        noul = await self._decision_judge_engine.ask(messages, params, **kwargs)
        triggered = noul >= params.threshold
        logger.info(
            'Decision judge on route=%s: noul=%s, threshold=%s, triggered=%s',
            route_config.route_name,
            noul,
            params.threshold,
            triggered,
        )
        if triggered:
            phase = kwargs.get('where')
            _reason_payload_ctx.set(
                {
                    'kind': 'decision_judge',
                    **_window_payload(_judge_texts(messages, kwargs)),
                    'phase': getattr(phase, 'name', None),
                    # Extra fields (for logs), sanitized out from API responses
                    'model_id': params.model_id,
                    'fallback_model_id': params.fallback_model_id,
                    'noul': noul,
                    'threshold': params.threshold,
                }
            )
        return triggered

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
        items = _indexed_texts(messages, kwargs.get('message_indices'))
        blob, _ = _blob_with_spans(items)
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
            phase = kwargs.get('where')
            _reason_payload_ctx.set(
                {
                    'kind': 'guardrails_ai',
                    'value': params.guard_name,
                    **_window_payload(items),
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
        count_judge_usage: JudgeUsageCounter | None = None,
        windowed: bool = True,
        skip: int = 0,
    ) -> SoftBlockInfo | None:
        """Apply guardrails to messages and return SoftBlockInfo on SOFT_BLOCK.

        ``windowed`` is False on calls with no conversation (embeddings,
        decision models): every guardrail then reads every message. ``skip``
        is how many leading messages the gateway added (its system prompt).
        They are not checked and do not count in the message indexes.
        """
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
            'parent_span': trace.get_current_span(),
            'count_judge_usage': count_judge_usage,
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

            selected = _select_messages(
                messages, guardrail, where, windowed=windowed, skip=skip
            )
            if not selected:
                logger.debug(
                    'Guardrail %s: no messages in history=%s roles=%s, skipping.',
                    guardrail.name,
                    guardrail.history,
                    guardrail.message_roles,
                )
                continue

            try:
                token = _reason_payload_ctx.set(None)
                is_triggered = await check_function(
                    [m for _, m in selected],
                    guardrail.parameters,
                    route_config,
                    message_roles=guardrail.message_roles,
                    # Indexes in the client's own list.
                    message_indices=[i - skip for i, _ in selected],
                    **kwargs,
                )
            except Exception as e:
                logger.error('Error applying guardrail %s: %s', guardrail.name, e)
                raise
            finally:
                reason_payload = _reason_payload_ctx.get()
                _reason_payload_ctx.reset(token)

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
                reason_payload=reason_payload,
            )
            if soft_block is not None:
                return soft_block
            if should_stop:
                return None
            # WARN/INFO: keep evaluating remaining guardrails
            continue

        return None

    @staticmethod
    def _indices_for_logs(reason_payload: dict) -> str:
        mi = reason_payload.get('message_indices')
        if mi:
            return f' message_indices={mi}'
        return ''

    @staticmethod
    def _format_presidio_reason_for_logs(reason_payload: dict) -> str | None:
        et = reason_payload.get('entity_type')
        val = reason_payload.get('value')
        if et is None or val is None:
            return None
        s = f'presidio entity_type={_trunc(repr(et))} value={_trunc(repr(val))}'
        s += GuardrailCheck._indices_for_logs(reason_payload)
        excerpt = reason_payload.get('context')
        if isinstance(excerpt, str) and excerpt:
            s += f' context="{_trunc(excerpt, max_len=120)}"'
        return s

    @staticmethod
    def _format_check_reason_for_logs(reason_payload: dict | None) -> str | None:
        """Return a readable reason string for logs from a reason payload."""
        if not isinstance(reason_payload, dict):
            return None
        kind = reason_payload.get('kind')
        mi = reason_payload.get('message_indices')
        if kind == 'presidio':
            return GuardrailCheck._format_presidio_reason_for_logs(reason_payload)
        if kind in ('starts_with', 'ends_with', 'contains'):
            val = reason_payload.get('value')
            if kind and val is not None and mi is not None:
                s = f'{kind} value={_trunc(repr(val))} message_indices={mi}'
            else:
                return None
        elif kind == 'regex':
            pat = reason_payload.get('pattern')
            if pat is not None and mi is not None:
                s = f'regex pattern={_trunc(repr(pat))} message_indices={mi}'
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
            s += GuardrailCheck._indices_for_logs(reason_payload)
            excerpt = reason_payload.get('context')
            if isinstance(excerpt, str) and excerpt:
                s += f' text="{_trunc(excerpt, max_len=120)}"'
            return s
        elif kind == 'decision_judge':
            s = 'decision_judge'
            for key in ('model_id', 'fallback_model_id', 'noul', 'threshold', 'phase'):
                value = reason_payload.get(key)
                if value is not None:
                    s += f' {key}={_trunc(repr(value), max_len=120)}'
            s += GuardrailCheck._indices_for_logs(reason_payload)
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
            s += GuardrailCheck._indices_for_logs(reason_payload)
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
        reason_payload: dict | None = None,
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

        # Capture telemetry tracing attributes for triggered guardrails on the active span
        try:
            span = trace.get_current_span()
            if span and span.is_recording():
                span.set_attribute('guardrail.triggered.name', guardrail.name)
                span.set_attribute('guardrail.triggered.type', guardrail.type.name)
                span.set_attribute('guardrail.triggered.where', where.name)
                span.set_attribute(
                    'guardrail.triggered.behavior', guardrail.behavior.name
                )

                # Expose specific match reason details (value/pattern) to tracing attributes
                if reason_payload:
                    if 'value' in reason_payload and reason_payload['value']:
                        span.set_attribute(
                            'guardrail.triggered.value', str(reason_payload['value'])
                        )
                    if 'pattern' in reason_payload and reason_payload['pattern']:
                        span.set_attribute(
                            'guardrail.triggered.pattern',
                            str(reason_payload['pattern']),
                        )
                    if (
                        'entity_type' in reason_payload
                        and reason_payload['entity_type']
                    ):
                        span.set_attribute(
                            'guardrail.triggered.entity_type',
                            str(reason_payload['entity_type']),
                        )
                    if 'reasoning' in reason_payload and reason_payload['reasoning']:
                        span.set_attribute(
                            'guardrail.triggered.reasoning',
                            str(reason_payload['reasoning']),
                        )
                    if 'context' in reason_payload and reason_payload['context']:
                        span.set_attribute(
                            'guardrail.triggered.context',
                            str(reason_payload['context']),
                        )
                    # The message that matched, or every message a judge read.
                    mi = reason_payload.get('message_indices')
                    if mi:
                        span.set_attribute('guardrail.triggered.message_indices', mi)
        except Exception:
            pass

        # Expose structured details via GuardrailBadRequest.reason (surfaced in error.param.reason),
        # and also append a readable reason to logs for easier debugging.
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
        count_judge_usage: JudgeUsageCounter | None = None,
        skip: int = 0,
    ) -> bool:
        """Evaluate only WARN-behavior guardrails without emitting events/logs.
        Used to surface a response header for non-blocking guardrails.
        ``skip`` works as in apply_guardrails.
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
            'parent_span': trace.get_current_span(),
            'count_judge_usage': count_judge_usage,
        }

        for guardrail in check_guardrails:
            check_function = self._guardrail_check_mapping.get(guardrail.type)
            if not check_function:
                continue
            selected = _select_messages(messages, guardrail, where, skip=skip)
            if not selected:
                continue
            try:
                if await check_function(
                    [m for _, m in selected],
                    guardrail.parameters,
                    route_config,
                    message_roles=guardrail.message_roles,
                    # Indexes in the client's own list.
                    message_indices=[i - skip for i, _ in selected],
                    **kwargs,
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
