"""The guardrails a request is screened by: its input before the model, the
model's reply after.

A project's ``Guardrails`` hold its guardrail definitions and what runs them.
``for_route`` picks a route's own, once, when the route is built
(``RouteGuardrails``); each request then gets a ``RequestGuardrails``, bound to
its caller and to the limits a judge's call is charged to (ADR 0006).

The methods carry the order ADR 0010 sets: ``redact_input`` runs before
routing, ``check_input`` after the route's system prompt is injected, and
``screen_input`` runs both where nothing comes between. ``screen_output``
redacts, then checks, the reply. What they read comes in a payload adapter
(``Conversation``, ``Texts``, ``Reply``, ``ResponsesReply``), so one
implementation serves every endpoint. A soft block comes back as a
``SoftBlock``: the module never builds a response, each endpoint renders the
block in its own shape.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
import logging
from typing import Generic, Protocol, Self, TypeVar

from radicalbit_ai_gateway.guardrails.guardrail_check import CheckResult, GuardrailCheck
from radicalbit_ai_gateway.guardrails.guardrail_redact import GuardrailRedact
from radicalbit_ai_gateway.guardrails.judges.decision_judge_engine import (
    DecisionJudgeEngine,
)
from radicalbit_ai_gateway.guardrails.judges.judge_engine import (
    JudgeEngine,
    JudgeUsageCounter,
)
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.llm.messages import AIMessage, BaseMessage, HumanMessage
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.guardrails import (
    Guardrail,
    GuardrailClass,
    GuardrailWhereType,
)
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.models.request_identity import RequestIdentity
from radicalbit_ai_gateway.models.soft_block_info import SoftBlock
from radicalbit_ai_gateway.responses.output import ResponsesOutput
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import (
    GatewayInternalError,
    GuardrailBadRequest,
    JudgeInternalError,
)
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    set_operation_category,
)

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)

INPUT = GuardrailWhereType.INPUT
OUTPUT = GuardrailWhereType.OUTPUT

TRIGGERED = 'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED'
WARN = 'X-RB-AIGATEWAY-GUARDRAILS-WARN'


@dataclass(frozen=True)
class GuardrailFlags:
    """What the guardrails did to a request, as its response headers tell it.

    ``*_warned``: a redaction changed a text or a WARN guardrail triggered.
    ``*_blocked``: a soft block answered in place of the model.
    """

    input_warned: bool = False
    input_blocked: bool = False
    output_warned: bool = False
    output_blocked: bool = False

    def __or__(self, other: GuardrailFlags) -> GuardrailFlags:
        """Return what either did."""
        return GuardrailFlags(
            input_warned=self.input_warned or other.input_warned,
            input_blocked=self.input_blocked or other.input_blocked,
            output_warned=self.output_warned or other.output_warned,
            output_blocked=self.output_blocked or other.output_blocked,
        )

    def headers(self) -> dict[str, str]:
        """Return the guardrail headers of the response."""
        headers: dict[str, str] = {}
        if self.input_blocked or self.output_blocked:
            headers[TRIGGERED] = 'true'
            if self.input_blocked:
                headers['X-RB-AIGATEWAY-GUARDRAILS-INPUT-TRIGGERED'] = 'true'
            if self.output_blocked:
                headers['X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-TRIGGERED'] = 'true'
        if self.input_warned or self.output_warned:
            headers[WARN] = 'true'
            if self.input_warned:
                headers['X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN'] = 'true'
            if self.output_warned:
                headers['X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN'] = 'true'
        return headers


# ---------------------------------------------------------------------------
# Payloads: what the guardrails read, and where a redacted text goes back
# ---------------------------------------------------------------------------


class Payload(Protocol):
    #: False on a call with no conversation: every guardrail reads every text.
    windowed: bool
    #: How many leading messages the gateway added (its system prompt). They
    #: are not checked and do not count in the message indexes.
    skip: int

    def messages(self) -> list[BaseMessage]: ...

    def with_messages(self, messages: list[BaseMessage]) -> Self: ...


P = TypeVar('P', bound=Payload)


@dataclass(frozen=True)
class Conversation:
    """The messages of a chat or Responses request."""

    items: list[BaseMessage]
    skip: int = 0
    windowed = True

    def messages(self) -> list[BaseMessage]:
        return self.items

    def with_messages(self, messages: list[BaseMessage]) -> Conversation:
        return replace(self, items=messages)


@dataclass(frozen=True)
class Texts:
    """Texts with no conversation: embedding inputs, a decision's strings."""

    items: list[str]
    skip = 0
    windowed = False

    def messages(self) -> list[BaseMessage]:
        return [HumanMessage(content=text) for text in self.items]

    def with_messages(self, messages: list[BaseMessage]) -> Texts:
        return Texts(
            [
                m.content if isinstance(m.content, str) else str(m.content)
                for m in messages
            ]
        )


@dataclass(frozen=True)
class Reply:
    """A chat model's reply text. An empty reply is checked, not redacted."""

    text: str | None
    usage: dict | None = None
    skip = 0
    windowed = True

    def messages(self) -> list[BaseMessage]:
        return [AIMessage(content=self.text, usage_metadata=self.usage)]

    def with_messages(self, messages: list[BaseMessage]) -> Reply:
        return replace(self, text=messages[0].content)

    @property
    def redactable(self) -> bool:
        return bool(self.text)


@dataclass(frozen=True)
class ResponsesReply:
    """The output message texts of a Responses API response."""

    output: ResponsesOutput
    items: list[BaseMessage]
    skip = 0
    windowed = True
    redactable = True

    @classmethod
    def of(cls, response: dict) -> ResponsesReply:
        output = ResponsesOutput(response)
        return cls(output, output.messages())

    def messages(self) -> list[BaseMessage]:
        return self.items

    def with_messages(self, messages: list[BaseMessage]) -> ResponsesReply:
        return replace(self, items=messages)

    def response(self) -> dict:
        """Return the response with the texts of this reply written in."""
        self.output.write_back(self.items)
        return self.output.response


@dataclass(frozen=True)
class Screened(Generic[P]):
    """A payload after guardrails: what they changed, flagged, or blocked."""

    payload: P
    flags: GuardrailFlags = GuardrailFlags()
    soft_block: SoftBlock | None = None


def _changed(before: list[BaseMessage], after: list[BaseMessage]) -> bool:
    return len(before) != len(after) or any(
        b.content != a.content for b, a in zip(before, after)
    )


# ---------------------------------------------------------------------------
# A project's, a route's and a request's guardrails
# ---------------------------------------------------------------------------


class Guardrails:
    """A project's guardrail definitions, and what runs them."""

    def __init__(
        self,
        presidio_engine: PresidioEngine,
        judge_engine: JudgeEngine,
        cost_service: CostService,
        guardrails: Sequence[Guardrail] | None = None,
        chat_models_by_id: dict[str, Model] | None = None,
        decision_judge_engine: DecisionJudgeEngine | None = None,
    ):
        self._by_name = {g.name: g for g in guardrails or []}
        self._redact = GuardrailRedact(presidio_engine=presidio_engine)
        self._check = GuardrailCheck(
            presidio_engine=presidio_engine,
            judge_engine=judge_engine,
            cost_service=cost_service,
            chat_models_by_id=chat_models_by_id,
            decision_judge_engine=decision_judge_engine,
        )

    def for_route(self, config: GatewayRouteConfig) -> RouteGuardrails:
        """Return the guardrails of a route: its enabled ones, by phase and class."""

        def pick(where: GuardrailWhereType, kind: GuardrailClass):
            return tuple(
                g
                for name in config.guardrails or []
                if (g := self._by_name.get(name))
                and g.enabled
                and g.guardrail_class() == kind
                and g.where in (where, GuardrailWhereType.IO)
            )

        return RouteGuardrails(
            route_name=config.route_name,
            input_redact=pick(INPUT, GuardrailClass.REDACT),
            input_check=pick(INPUT, GuardrailClass.CHECK),
            output_redact=pick(OUTPUT, GuardrailClass.REDACT),
            output_check=pick(OUTPUT, GuardrailClass.CHECK),
            unknown=tuple(n for n in config.guardrails or [] if n not in self._by_name),
            redact=self._redact,
            check=self._check,
        )


@dataclass(frozen=True)
class RouteGuardrails:
    """A route's guardrails, built once when its configuration is loaded."""

    route_name: str = ''
    input_redact: tuple[Guardrail, ...] = ()
    input_check: tuple[Guardrail, ...] = ()
    output_redact: tuple[Guardrail, ...] = ()
    output_check: tuple[Guardrail, ...] = ()
    #: Names the route lists that the project does not define.
    unknown: tuple[str, ...] = ()
    redact: GuardrailRedact | None = None
    check: GuardrailCheck | None = None

    @property
    def has_output(self) -> bool:
        """Whether the model's whole reply must be known before it is sent."""
        return bool(self.output_redact or self.output_check)

    def for_request(
        self, identity: RequestIdentity, charge: JudgeUsageCounter
    ) -> RequestGuardrails:
        return RequestGuardrails(self, identity, charge)


class RequestGuardrails:
    """The guardrails one request is screened by."""

    def __init__(
        self,
        route: RouteGuardrails,
        identity: RequestIdentity,
        charge: JudgeUsageCounter,
    ) -> None:
        self._route = route
        self._identity = identity
        self._charge = charge

    async def redact_input(self, payload: P) -> Screened[P]:
        """Apply the input REDACT guardrails. Runs before routing (ADR 0010)."""
        if not self._route.input_redact:
            return Screened(payload)
        set_operation_category(OperationCategory.GUARDRAIL_INPUT)
        before = payload.messages()
        after = await self._redact(self._route.input_redact, payload, INPUT)
        return Screened(
            payload.with_messages(after),
            GuardrailFlags(input_warned=_changed(before, after)),
        )

    async def check_input(
        self, payload: P, flags: GuardrailFlags = GuardrailFlags()
    ) -> Screened[P]:
        """Apply the input CHECK guardrails, after the system prompt is
        injected (ADR 0010). ``flags`` are those of the redaction.
        """
        if not self._route.input_check:
            return Screened(payload, flags)
        set_operation_category(OperationCategory.GUARDRAIL_INPUT)
        result = await self._check(self._route.input_check, payload, INPUT)
        if result.soft_block:
            return Screened(
                payload, flags | GuardrailFlags(input_blocked=True), result.soft_block
            )
        return Screened(payload, flags | GuardrailFlags(input_warned=result.warned))

    async def screen_input(self, payload: P) -> Screened[P]:
        """Redact, then check, an input that nothing reads in between."""
        redacted = await self.redact_input(payload)
        return await self.check_input(redacted.payload, redacted.flags)

    async def screen_output(self, reply: P) -> Screened[P]:
        """Redact, then check, a model's reply. A soft block flags the
        output as both blocked and warned.
        """
        route = self._route
        if not route.has_output or not reply.messages():
            return Screened(reply)
        set_operation_category(OperationCategory.GUARDRAIL_OUTPUT)
        warned = False
        if route.output_redact and getattr(reply, 'redactable', True):
            before = reply.messages()
            after = await self._redact(route.output_redact, reply, OUTPUT)
            warned = _changed(before, after)
            reply = reply.with_messages(after)
        if route.output_check:
            result = await self._check(route.output_check, reply, OUTPUT)
            if result.soft_block:
                return Screened(
                    reply,
                    GuardrailFlags(output_warned=True, output_blocked=True),
                    result.soft_block,
                )
            warned = warned or result.warned
        return Screened(reply, GuardrailFlags(output_warned=warned))

    async def _redact(
        self, guardrails: tuple[Guardrail, ...], payload: Payload, where
    ) -> list[BaseMessage]:
        return await self._route.redact.apply(
            identity=self._identity,
            guardrails=guardrails,
            unknown=self._route.unknown,
            messages=payload.messages(),
            where=where,
            windowed=payload.windowed,
        )

    async def _check(
        self, guardrails: tuple[Guardrail, ...], payload: Payload, where
    ) -> CheckResult:
        try:
            return await self._route.check.apply(
                identity=self._identity,
                guardrails=guardrails,
                unknown=self._route.unknown,
                messages=payload.messages(),
                where=where,
                count_judge_usage=self._charge,
                windowed=payload.windowed,
                skip=payload.skip,
            )
        except (GuardrailBadRequest, JudgeInternalError):
            raise
        except Exception as e:
            logger.error('Unexpected error during guardrail application: %s', e)
            raise GatewayInternalError(
                f'Error during guardrail application: {e}'
            ) from e
