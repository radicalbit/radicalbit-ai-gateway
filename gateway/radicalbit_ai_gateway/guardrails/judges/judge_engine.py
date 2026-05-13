import logging
import time

from langchain.chat_models.base import init_chat_model
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import Runnable

from radicalbit_ai_gateway.events.events_processor import emit_event
from radicalbit_ai_gateway.metrics.define_metrics import (
    fallbacks_triggered_counter,
    invocations_latency_histogram,
    model_invocations_counter,
    tokens_per_request_histogram_input,
    tokens_per_request_histogram_output,
    total_tokens_counter_input,
    total_tokens_counter_output,
)
from radicalbit_ai_gateway.models.event_payload import (
    FallbackEventPayload,
    InputTokenProcessedPayload,
    ModelInvocationPayload,
    OutputTokenProcessedPayload,
)
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.guardrails import JudgeParameter
from radicalbit_ai_gateway.models.judge_invocation_result import JudgeInvocationResult
from radicalbit_ai_gateway.models.judge_result import JudgeResult
from radicalbit_ai_gateway.models.judge_runtime_config import JudgeRuntimeConfig
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import (
    JudgeInternalError,
    JudgeOutputTruncatedError,
    JudgeParsingError,
)
from radicalbit_ai_gateway.utils.judge import (
    extract_content_for_judge,
    extract_judge_result,
    extract_media_blocks_for_judge,
)
from radicalbit_ai_gateway.utils.parse_provider_and_model import (
    parse_provider_and_model,
)

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


class JudgeEngine:
    """Engine for executing guardrails with LLM as a judge."""

    def __init__(
        self,
        prompt_manager: PromptManager,
        httpx_client=None,
    ):
        self.prompt_manager = prompt_manager
        self._model_cache: dict[str, Runnable] = {}
        self.httpx_client = httpx_client

    async def execute_judge(
        self,
        messages: list[BaseMessage],
        judge_parameter: JudgeParameter,
        primary_model: Model,
        cost_service: CostService,
        fallback_model: Model | None = None,
        **kwargs,
    ) -> JudgeResult:
        judge_runtime_config = JudgeRuntimeConfig(
            model_id=judge_parameter.model_id,
            fallback_model_id=judge_parameter.fallback_model_id,
            temperature=judge_parameter.temperature,
            max_tokens=judge_parameter.max_tokens,
            prompt_ref=judge_parameter.prompt_ref,
            include_reasoning=judge_parameter.include_reasoning,
        )
        media_blocks: list[dict] = (
            extract_media_blocks_for_judge(messages, **kwargs)
            if judge_parameter.include_media
            else []
        )
        prompt_template = self._build_prompt_template(
            judge_runtime_config, include_media=bool(media_blocks)
        )
        content = extract_content_for_judge(messages, **kwargs)

        logger.debug(
            'Invoking judge with prompt_ref=%s, include_reasoning=%s, media_blocks=%d',
            judge_parameter.prompt_ref,
            judge_parameter.include_reasoning,
            len(media_blocks),
        )

        return await self._invoke_judge_model(
            primary_model=primary_model,
            fallback_model=fallback_model,
            judge_runtime_config=judge_runtime_config,
            prompt_template=prompt_template,
            content=content,
            media_blocks=media_blocks,
            cost_service=cost_service,
            **kwargs,
        )

    def _build_prompt_template(
        self, config: JudgeRuntimeConfig, include_media: bool = False
    ) -> PromptTemplate:
        base_template = self.prompt_manager.get_judge_prompt(config.prompt_ref)
        reasoning_note = (
            "You may include a short reasoning in the 'reasoning' field."
            if config.include_reasoning
            else "Do NOT include any reasoning. The 'reasoning' field MUST be null or omitted."
        )
        content_label = 'Content Under Review' if include_media else 'Text Under Review'
        return PromptTemplate(
            template=f"""{base_template.strip()}
{reasoning_note}
---
{content_label}:
{{content}}
""",
            input_variables=['content'],
        )

    async def _invoke_judge_model(
        self,
        primary_model: Model,
        fallback_model: Model | None,
        judge_runtime_config: JudgeRuntimeConfig,
        prompt_template: PromptTemplate,
        content: str,
        cost_service: CostService,
        media_blocks: list[dict] | None = None,
        **kwargs,
    ) -> JudgeResult:
        _media = media_blocks or []
        try:
            return await self._invoke_and_record_metrics(
                model=primary_model,
                judge_runtime_config=judge_runtime_config,
                content=content,
                prompt_template=prompt_template,
                media_blocks=_media,
                cost_service=cost_service,
                **kwargs,
            )
        except (JudgeOutputTruncatedError, JudgeParsingError) as judge_err:
            logger.warning('Primary judge failed with recoverable error: %s', judge_err)
            primary_err = judge_err
            if not fallback_model:
                logger.error('No fallback model defined. Raising judge error.')
                raise
        except Exception as err:
            # Unexpected errors (network, auth, etc.) - try fallback or raise
            logger.warning('Primary model failed with unexpected error: %s', err)
            primary_err = err
            if not fallback_model:
                logger.error('No fallback model defined. Raising judge error.')
                raise JudgeInternalError(
                    f'Primary judge model failed: {err}',
                    log_message=f'Primary judge model failed unexpectedly: {err}',
                    model_id=primary_model.model_id,
                ) from err

        # Fallback execution
        try:
            logger.info(
                'Attempting fallback model %s after primary model %s failed',
                fallback_model.model_id,
                primary_model.model_id,
            )
            return await self._invoke_and_record_metrics(
                model=fallback_model,
                judge_runtime_config=judge_runtime_config,
                content=content,
                prompt_template=prompt_template,
                media_blocks=_media,
                fallback_triggerd=True,
                target_model_id=primary_model.model_id,
                cost_service=cost_service,
                **kwargs,
            )
        except (JudgeOutputTruncatedError, JudgeParsingError) as fallback_err:
            logger.error(
                'Both primary and fallback judges failed: primary=%s | fallback=%s',
                str(primary_err),
                str(fallback_err),
            )
            raise JudgeInternalError(
                'Both primary and fallback judge models failed to produce valid output',
                log_message=(
                    f'Both primary and fallback judges failed: '
                    f'primary={primary_err}, fallback={fallback_err}'
                ),
                model_id=fallback_model.model_id,
            ) from fallback_err
        except Exception as fallback_err:
            logger.error(
                'Both primary and fallback models failed: %s | %s',
                str(primary_err),
                str(fallback_err),
            )
            raise JudgeInternalError(
                'Both primary and fallback judge models failed',
                log_message=(
                    f'Both primary and fallback models failed: '
                    f'primary={primary_err}, fallback={fallback_err}'
                ),
                model_id=fallback_model.model_id,
            ) from fallback_err

    async def _invoke_and_record_metrics(
        self,
        model: Model,
        judge_runtime_config: JudgeRuntimeConfig,
        content: str,
        prompt_template: PromptTemplate,
        cost_service: CostService,
        media_blocks: list[dict] | None = None,
        fallback_triggerd: bool = False,
        target_model_id: str = '',
        **kwargs,
    ) -> JudgeResult:
        invocation = await self._invoke_model(
            model=model,
            judge_runtime_config=judge_runtime_config,
            content=content,
            prompt_template=prompt_template,
            media_blocks=media_blocks or [],
        )
        self._record_metrics(
            invocation=invocation,
            model=model,
            fallback_triggered=fallback_triggerd,
            target_model_id=target_model_id,
            cost_service=cost_service,
            **kwargs,
        )
        return extract_judge_result(invocation.result, model.model_id)

    async def _invoke_model(
        self,
        model: Model,
        judge_runtime_config: JudgeRuntimeConfig,
        content: str,
        prompt_template: PromptTemplate,
        media_blocks: list[dict] | None = None,
    ) -> JudgeInvocationResult:
        structured_model = self._get_or_create_model(judge_runtime_config, model)

        start_time = time.monotonic()
        if media_blocks:
            judge_text = prompt_template.format(content=content)
            human_content: list[dict] = [
                {'type': 'text', 'text': judge_text},
                *media_blocks,
            ]
            result = await structured_model.ainvoke(
                [HumanMessage(content=human_content)]
            )
        else:
            generation_chain = prompt_template | structured_model
            result = await generation_chain.ainvoke({'content': content})
        latency_ms = (time.monotonic() - start_time) * 1000

        raw_response = result.get('raw')

        token_input_count: int | None = None
        token_output_count: int | None = None
        cached_token_count: int | None = None

        if isinstance(raw_response, AIMessage) and raw_response.response_metadata:
            token_usage = raw_response.response_metadata.get('token_usage')
            if token_usage:
                prompt_tokens_details = token_usage.get('prompt_tokens_details')
                if prompt_tokens_details:
                    cached_token_count = prompt_tokens_details.get('cached_tokens')

        if isinstance(raw_response, AIMessage) and raw_response.usage_metadata:
            token_input_count = raw_response.usage_metadata.get('input_tokens')
            token_output_count = raw_response.usage_metadata.get('output_tokens')

        return JudgeInvocationResult(
            result=result,
            latency_ms=latency_ms,
            token_input_count=token_input_count,
            token_output_count=token_output_count,
            cached_token_count=cached_token_count,
        )

    def _get_or_create_model(
        self, config: JudgeRuntimeConfig, model: Model
    ) -> Runnable:
        cache_key = f'{model.model_id}:{config.temperature}:{config.max_tokens}'
        if cache_key not in self._model_cache:
            provider, model_name = parse_provider_and_model(model.model)
            params = dict(
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                **(
                    model.credentials.model_dump(exclude_none=True)
                    if model.credentials
                    else {}
                ),
            )
            if provider not in ('anthropic', 'mistralai'):
                params['http_async_client'] = self.httpx_client
            self._model_cache[cache_key] = init_chat_model(
                model=f'{provider}:{model_name}',
                **params,
            ).with_structured_output(schema=JudgeResult, include_raw=True)
        return self._model_cache[cache_key]

    def _record_metrics(
        self,
        invocation: JudgeInvocationResult,
        model: Model,
        cost_service: CostService,
        fallback_triggered: bool = False,
        target_model_id: str = '',
        **kwargs,
    ) -> None:
        route_name = kwargs.get('route_name', 'unknown_route')
        request_uuid = kwargs.get('request_uuid', 'unknown_request')
        api_key_uuid = kwargs.get('api_key_uuid', 'unknown_api_key')
        group_uuid = kwargs.get('group_uuid', 'unknown_group_uuid')
        api_key_name = kwargs.get('api_key_name', 'unknown_api_key_name')
        group_name = kwargs.get('group_name', 'unknown_group_name')
        project_uuid = kwargs.get('project_uuid', '')
        project_name = kwargs.get('project_name', '')

        if not fallback_triggered:
            emit_event(
                ModelInvocationPayload(
                    request_uuid=request_uuid,
                    event_type=EventType.MODEL_INVOCATION,
                    route_name=route_name,
                    value=1.0,
                    api_key_uuid=api_key_uuid,
                    api_key_name=api_key_name,
                    group_uuid=group_uuid,
                    group_name=group_name,
                    project_uuid=project_uuid,
                    project_name=project_name,
                    model_id=model.model_id,
                    model_type='chat-model',
                    is_judge=True,
                )
            )
            model_invocations_counter.add(
                1, {'route_name': route_name, 'model_name': model.model_id}
            )
        else:
            emit_event(
                FallbackEventPayload(
                    request_uuid=request_uuid,
                    event_type=EventType.FALLBACK,
                    route_name=route_name,
                    value=1.0,
                    api_key_uuid=api_key_uuid,
                    group_uuid=group_uuid,
                    api_key_name=api_key_name,
                    group_name=group_name,
                    project_uuid=project_uuid,
                    project_name=project_name,
                    target=target_model_id,
                    fallback=model.model_id,
                    is_judge=True,
                )
            )
            fallbacks_triggered_counter.add(
                1,
                {
                    'route_name': route_name,
                    'target': target_model_id,
                    'fallback': model.model_id,
                },
            )

        invocations_latency_histogram.record(
            invocation.latency_ms,
            {'route_name': route_name, 'model_name': model.model_id},
        )

        if invocation.cached_token_count and invocation.cached_token_count > 0:
            cost = cost_service.compute_cost(
                model_id=model.model_id,
                token_processed=invocation.cached_token_count,
                where='cached',
            )
            emit_event(
                InputTokenProcessedPayload(
                    request_uuid=request_uuid,
                    event_type=EventType.INPUT_TOKEN_PROCESSED,
                    route_name=route_name,
                    value=invocation.cached_token_count,
                    api_key_uuid=api_key_uuid,
                    group_uuid=group_uuid,
                    api_key_name=api_key_name,
                    group_name=group_name,
                    project_uuid=project_uuid,
                    project_name=project_name,
                    cost=cost,
                    model_id=model.model_id,
                    model_type='chat-model',
                    is_cached_tokens=True,
                    is_judge=True,
                )
            )
            total_tokens_counter_input.add(
                invocation.cached_token_count,
                {'route_name': route_name, 'model_name': model.model_id},
            )
            tokens_per_request_histogram_input.record(
                invocation.cached_token_count,
                {'route_name': route_name, 'model_name': model.model_id},
            )

        if invocation.token_input_count:
            cost = cost_service.compute_cost(
                token_processed=invocation.token_input_count
                - (invocation.cached_token_count or 0),
                model_id=model.model_id,
                where='input',
            )
            emit_event(
                InputTokenProcessedPayload(
                    request_uuid=request_uuid,
                    event_type=EventType.INPUT_TOKEN_PROCESSED,
                    route_name=route_name,
                    value=invocation.token_input_count,
                    api_key_uuid=api_key_uuid,
                    group_uuid=group_uuid,
                    api_key_name=api_key_name,
                    group_name=group_name,
                    project_uuid=project_uuid,
                    project_name=project_name,
                    cost=cost,
                    model_id=model.model_id,
                    model_type='chat-model',
                    is_judge=True,
                )
            )
            total_tokens_counter_input.add(
                invocation.token_input_count,
                {'route_name': route_name, 'model_name': model.model_id},
            )
            tokens_per_request_histogram_input.record(
                invocation.token_input_count,
                {'route_name': route_name, 'model_name': model.model_id},
            )

        if invocation.token_output_count:
            cost = cost_service.compute_cost(
                token_processed=invocation.token_output_count,
                model_id=model.model_id,
                where='output',
            )
            emit_event(
                OutputTokenProcessedPayload(
                    request_uuid=request_uuid,
                    event_type=EventType.OUTPUT_TOKEN_PROCESSED,
                    route_name=route_name,
                    value=invocation.token_output_count,
                    api_key_uuid=api_key_uuid,
                    group_uuid=group_uuid,
                    api_key_name=api_key_name,
                    group_name=group_name,
                    project_uuid=project_uuid,
                    project_name=project_name,
                    cost=cost,
                    model_id=model.model_id,
                    model_type='chat-model',
                    is_judge=True,
                )
            )
            total_tokens_counter_output.add(
                invocation.token_output_count,
                {'route_name': route_name, 'model_name': model.model_id},
            )
            tokens_per_request_histogram_output.record(
                invocation.token_output_count,
                {'route_name': route_name, 'model_name': model.model_id},
            )
