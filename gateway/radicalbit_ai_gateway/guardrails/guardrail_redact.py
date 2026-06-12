import asyncio
from collections.abc import Awaitable, Callable, Mapping
import logging
from typing import Any

from langchain_core.messages import BaseMessage
from traceloop.sdk.decorators import task, workflow

from radicalbit_ai_gateway.events.events_processor import emit_event
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.metrics.define_metrics import guardrails_triggered_counter
from radicalbit_ai_gateway.models.event_payload import GuardrailEventPayload
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.guardrails import (
    Guardrail,
    GuardrailClass,
    GuardrailType,
    GuardrailWhereType,
    RedactParameter,
)
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import GuardrailBadRequest

app_config = get_app_config()
logging_config_dict = app_config.log_config.model_dump()
logger = logging.getLogger(app_config.log_config.logger_name)

GuardrailRedactFunction = Callable[
    [list[BaseMessage], RedactParameter], Awaitable[tuple[list[BaseMessage], bool]]
]


def _with_content(msg: BaseMessage, new_content: Any) -> BaseMessage:
    """Create a copy of the message with updated content, preserving other fields.
    If not possible, falls back to mutating the instance (preserves special fields like tool_call_id).
    """
    if hasattr(msg, 'model_copy'):
        # LangChain messages (pydantic v2)
        try:
            return msg.model_copy(update={'content': new_content})
        except Exception:
            pass

    try:
        return msg.__class__(
            content=new_content,
            additional_kwargs=getattr(msg, 'additional_kwargs', {}),
            response_metadata=getattr(msg, 'response_metadata', {}),
        )
    except Exception:
        # fallback: mutate the object directly (useful for ToolMessage)
        try:
            msg.content = new_content
        except Exception:
            logger.debug('Unable to set new content on message; returning original.')
        return msg


async def _anonymize_text_with_presidio(
    text: str,
    language: str,
    entities: list,
    presidio_engine: PresidioEngine,
    backend: str = 'local',
    ahds=None,
) -> tuple[str, bool]:
    """Execute analyze + anonymize on a string.
    Returns (redacted_text, True) if changed, otherwise (original_text, False).
    """
    if not isinstance(text, str) or not text:
        return text, False

    try:
        analyzer = presidio_engine.get_analyzer(backend, ahds)
    except Exception:
        logger.exception('Failed to initialize Presidio analyzer (backend=%s)', backend)
        raise

    try:
        results = await asyncio.to_thread(
            analyzer.analyze,
            text=text,
            entities=entities,
            language=language,
        )
    except ValueError:
        logger.exception(
            'Presidio analyze failed (backend=%s, entities=%s, language=%s). '
            'Check that the requested entities are supported by the configured backend.',
            backend,
            entities,
            language,
        )
        raise

    if not results:
        return text, False

    # Run anonymization in thread pool
    anon_result = await asyncio.to_thread(
        presidio_engine.anonymizer.anonymize, text=text, analyzer_results=results
    )
    redacted = getattr(anon_result, 'text', None) or text
    return redacted, (redacted != text)


class GuardrailRedact:
    def __init__(
        self,
        presidio_engine: PresidioEngine,
        guardrails_by_name: dict[str, Guardrail] | None = None,
    ):
        self._presidio_engine = presidio_engine
        self._guardrails_by_name = guardrails_by_name or {}

        self._guardrail_redact_mapping: dict[GuardrailType, GuardrailRedactFunction] = {
            GuardrailType.PRESIDIO_ANONYMIZER: self._redact_presidio,
        }

    @task(name='redact_presidio')
    async def _redact_presidio(
        self, messages: list[BaseMessage], params: RedactParameter
    ) -> tuple[list[BaseMessage], bool]:
        """Redacts a list of messages using Presidio Anonymizer.
        - If content is a str: redacts the entire string.
        - If content is a list (multimodal): redacts only the parts where {"type": "text"}.
        - Other types of parts (file, image, etc.) remain unchanged.
        Returns (new_messages, something_was_redacted).
        """
        language = params.language
        entities = params.entities
        backend = params.backend
        ahds = params.ahds

        new_messages: list[BaseMessage] = []
        any_redacted = False

        for msg in messages:
            content = msg.content

            # Case 1: content is a string
            if isinstance(content, str):
                red_text, changed = await _anonymize_text_with_presidio(
                    content, language, entities, self._presidio_engine, backend, ahds
                )
                any_redacted = any_redacted or changed
                new_messages.append(_with_content(msg, red_text))

            # Case 2: content is a list (multimodal)
            elif isinstance(content, list):
                changed_here = False
                new_parts: list[Any] = []

                for p in content:
                    if isinstance(p, Mapping) and p.get('type') == 'text':
                        t = p.get('text')
                        if isinstance(t, str):
                            red_t, ch = await _anonymize_text_with_presidio(
                                t,
                                language,
                                entities,
                                self._presidio_engine,
                                backend,
                                ahds,
                            )
                            changed_here = changed_here or ch
                            np = dict(p)
                            np['text'] = red_t
                            new_parts.append(np)
                        else:
                            new_parts.append(p)
                    else:
                        new_parts.append(p)

                any_redacted = any_redacted or changed_here
                new_messages.append(_with_content(msg, new_parts))

            # Case 3: other types of content (e.g., tool calls)
            else:
                new_messages.append(msg)

        return new_messages, any_redacted

    @workflow(name='apply_redact_guardrails')
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
    ) -> list[BaseMessage]:
        redact_guardrails = self._get_redact_guardrails_for_route(
            route_config=route_config,
            where=where,
        )

        if not redact_guardrails:
            return messages

        messages_to_redact = messages

        for guardrail in redact_guardrails:
            logger.debug(
                'Evaluating guardrail: %s (type=%s, where=%s, behavior=%s)',
                guardrail.name,
                guardrail.type.name,
                guardrail.where.name,
                guardrail.behavior.name,
            )

            redact_fn = self._guardrail_redact_mapping.get(guardrail.type)
            if not redact_fn:
                raise GuardrailBadRequest(
                    f'Unknown guardrail type: {guardrail.type}', guardrail
                )

            redacted_messages, was_redacted = await redact_fn(
                messages_to_redact, guardrail.parameters
            )

            if was_redacted:
                attrs = {
                    'name': guardrail.name,
                    'type': guardrail.type.name,
                    'where': guardrail.where.name,
                    'parameters': str(guardrail.parameters),
                    'behavior': guardrail.behavior.name,
                }
                emit_event(
                    GuardrailEventPayload(
                        request_uuid=request_uuid,
                        api_key_uuid=api_key_uuid,
                        group_uuid=group_uuid,
                        api_key_name=api_key_name,
                        route_name=route_config.route_name,
                        value=1.0,
                        event_type=EventType.GUARDRAIL,
                        group_name=group_name,
                        project_uuid=project_uuid,
                        project_name=project_name,
                        name=guardrail.name,
                        type=guardrail.type.name,
                        where=guardrail.where.name,
                        parameters=str(guardrail.parameters),
                        behavior=guardrail.behavior.name,
                    )
                )
                guardrails_triggered_counter.add(
                    1, {'route_name': route_config.route_name, **attrs}
                )

                log_message = (
                    f'[GUARDRAIL TRIGGERED] [route={route_config.route_name}] '
                    f'[name={guardrail.name}] [type={guardrail.type.name}] '
                    f'[where={where.name}] [behavior={guardrail.behavior.name}]'
                )

                logger.warning(log_message)

            messages_to_redact = redacted_messages

        return messages_to_redact

    def _get_redact_guardrails_for_route(
        self,
        route_config: GatewayRouteConfig,
        where: GuardrailWhereType,
    ) -> list[Guardrail]:
        guardrail_names = route_config.guardrails or []
        guardrails: list[Guardrail] = []

        for gr_name in guardrail_names:
            guardrail = self._guardrails_by_name.get(gr_name)
            if not guardrail:
                logger.warning(
                    'Guardrail name %r not found for route %s',
                    gr_name,
                    route_config.route_name,
                )
                continue
            if not guardrail.enabled:
                continue
            if guardrail.guardrail_class() != GuardrailClass.REDACT:
                continue
            if guardrail.where not in (where, GuardrailWhereType.IO):
                continue
            guardrails.append(guardrail)

        return guardrails
