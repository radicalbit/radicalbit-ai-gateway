import datetime
from decimal import Decimal

from radicalbit_ai_gateway.models.caching import CacheConfig, Caching, SemanticCaching
from radicalbit_ai_gateway.models.credentials import Credentials
from radicalbit_ai_gateway.models.fallback import Fallback
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.guardrails import (
    Guardrail,
    GuardrailBehaviorType,
    GuardrailType,
    GuardrailWhereType,
    JudgeParameter,
)
from radicalbit_ai_gateway.models.limiting import (
    Limiting,
    LimitingAlgorithmType,
    RateLimiting,
    TokenLimiting,
)
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.models.routing import (
    DeterministicRoutingConfig,
    OutputMappingEntry,
    RoutingRuleType,
)


def get_default_cache_config() -> CacheConfig:
    return CacheConfig(redis_host='redis_host', redis_port=1234)


def get_default_fallback(
    target: str = 'openai', fallback_one: str = 'deepseek', fallback_two: str = 'azure'
) -> Fallback:
    return Fallback(target=target, fallbacks=[fallback_one, fallback_two])


def get_global_guardrails() -> list[Guardrail]:
    return [
        Guardrail(
            name='starts_with_check',
            type=GuardrailType.STARTS_WITH,
            description='Check words which starts with a specific word',
            where=GuardrailWhereType.INPUT,
            behavior=GuardrailBehaviorType.BLOCK,
            parameters={'values': ['ciao', 'buonasera']},
        ),
        Guardrail(
            name='keyword_block',
            type=GuardrailType.CONTAINS,
            description=None,
            where=GuardrailWhereType.OUTPUT,
            behavior=GuardrailBehaviorType.BLOCK,
            parameters={'values': ['ciao']},
        ),
        Guardrail(
            name='email_address_redaction',
            type=GuardrailType.REGEX,
            description=None,
            where=GuardrailWhereType.IO,
            behavior=GuardrailBehaviorType.BLOCK,
            parameters={
                'values': [r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z|a-z]{2,}\b']
            },
        ),
        Guardrail(
            name='uuid_block',
            type=GuardrailType.REGEX,
            description=None,
            where=GuardrailWhereType.INPUT,
            behavior=GuardrailBehaviorType.BLOCK,
            parameters={
                'values': [
                    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-5][0-9a-f]{3}-[089ab][0-9a-f]{3}-[0-9a-f]{12}$'
                ]
            },
        ),
    ]


def get_chat_models(
    first_model: str = 'openai/gpt-4o',
    second_model: str = 'azure/chatgpt-v-2',
    third_model: str = 'deepseek/deepseek-chat-2',
) -> list[Model]:
    return [
        Model(
            model_id='openai',
            model=first_model,
            credentials=Credentials(
                api_key='sk-123',
                api_base=None,
                api_version=None,
                azure_ad_token=None,
                project_id=None,
                region=None,
                organization='org-123',
            ),
            params={
                'temperature': 0.9,
                'max_tokens': 150,
                'seed': None,
                'top_p': 0.9,
                'logprobs': None,
                'top_logprobs': None,
            },
            retry_attempts=3,
            prompt=None,
            input_cost_per_million_tokens=Decimal('0.3'),
            output_cost_per_million_tokens=Decimal('0.6'),
            input_cached_cost_per_million_tokens=Decimal('0.03'),
        ),
        Model(
            model_id='azure',
            model=second_model,
            credentials=Credentials(
                api_key=None,
                api_base='https://openai-gpt-4-test-v-1.openai.azure.com/',
                api_version=datetime.datetime(
                    2023,
                    5,
                    15,
                    0,
                    0,
                    tzinfo=datetime.timezone(datetime.timedelta(0), 'Z'),
                ),
                azure_ad_token='sk-123',
                project_id=None,
                region=None,
            ),
            params={
                'temperature': 0.7,
                'max_tokens': 20,
                'seed': 12,
                'top_p': 0.9,
                'logprobs': None,
                'top_logprobs': None,
            },
            retry_attempts=3,
            prompt=None,
            input_cost_per_million_tokens=Decimal('0.2'),
            output_cost_per_million_tokens=Decimal('0.0'),
            input_cached_cost_per_million_tokens=Decimal('0.02'),
        ),
        Model(
            model_id='deepseek',
            model=third_model,
            credentials=Credentials(
                api_key='sk-123',
                api_base=None,
                api_version=None,
                azure_ad_token=None,
                project_id=None,
                region=None,
            ),
            params={
                'temperature': 0.7,
                'max_tokens': 1000,
                'seed': None,
                'top_p': 0.9,
                'logprobs': None,
                'top_logprobs': None,
            },
            retry_attempts=3,
            prompt=None,
            input_cost_per_million_tokens=Decimal('0.0'),
            output_cost_per_million_tokens=Decimal('0.4'),
            input_cached_cost_per_million_tokens=Decimal('0.0'),
        ),
    ]


def get_embedding_models(
    embedding_model: str = 'openai/text-embedding-3-small',
) -> list[Model]:
    return [
        Model(
            model_id='text-embedding-3-small',
            model=embedding_model,
            credentials=Credentials(api_key='sk-123'),
            input_cost_per_million_tokens=Decimal('0.0'),
            output_cost_per_million_tokens=Decimal('0.0'),
            input_cached_cost_per_million_tokens=Decimal('0.0'),
        )
    ]


def get_default_gateway(
    route_name: str = 'rb-gateway',
    fallback_one: Fallback = get_default_fallback('openai', 'deepseek'),
    fallback_two: Fallback = get_default_fallback('azure', 'openai', 'deepseek'),
):
    chat_models = get_chat_models()
    embedding_models = get_embedding_models()

    route = GatewayRouteConfig(
        route_name=route_name,
        chat_models=[m.model_id for m in chat_models],
        embedding_models=[m.model_id for m in embedding_models],
        fallback=[fallback_one, fallback_two],
        rate_limiting=RateLimiting(
            window_size=5,
            max_requests=2,
            max_token=None,
            algorithm=LimitingAlgorithmType.FIXED_WINDOW,
        ),
        token_limiting=TokenLimiting(
            input=Limiting(
                algorithm=LimitingAlgorithmType.FIXED_WINDOW,
                window_size='1 minute',
                max_requests=None,
                max_token=1000,
            ),
            output=Limiting(
                algorithm=LimitingAlgorithmType.FIXED_WINDOW,
                window_size='10 minutes',
                max_requests=None,
                max_token=500,
            ),
        ),
        guardrails=[g.name for g in get_global_guardrails()],
    )

    return GatewayConfig(
        chat_models=chat_models,
        embedding_models=embedding_models,
        routes={route_name: route},
        guardrails=get_global_guardrails(),
        cache=get_default_cache_config(),
    )


def get_default_gateway_without_features(route_name: str = 'rb-gateway'):
    chat_models = get_chat_models()
    embedding_models = get_embedding_models()

    route = GatewayRouteConfig(
        route_name=route_name,
        chat_models=[m.model_id for m in chat_models],
        embedding_models=[m.model_id for m in embedding_models],
        rate_limiting=RateLimiting(
            window_size=5,
            max_requests=2,
            max_token=None,
            algorithm=LimitingAlgorithmType.FIXED_WINDOW,
        ),
        token_limiting=TokenLimiting(
            input=Limiting(
                algorithm=LimitingAlgorithmType.FIXED_WINDOW,
                window_size='1 minute',
                max_requests=None,
                max_token=1000,
            ),
            output=Limiting(
                algorithm=LimitingAlgorithmType.FIXED_WINDOW,
                window_size='10 minutes',
                max_requests=None,
                max_token=500,
            ),
        ),
        caching=Caching(enabled=True, ttl=3600, type='exact'),
    )

    return GatewayConfig(
        chat_models=chat_models,
        embedding_models=embedding_models,
        routes={route_name: route},
        guardrails=get_global_guardrails(),
        cache=get_default_cache_config(),
    )


def get_default_gateway_with_caching(
    route_name: str = 'rb-gateway',
    fallback_one: Fallback = get_default_fallback('openai', 'deepseek'),
    fallback_two: Fallback = get_default_fallback('azure', 'openai', 'deepseek'),
):
    """Get a default gateway configuration with all features plus caching enabled on the route."""
    chat_models = get_chat_models()
    embedding_models = get_embedding_models()

    route = GatewayRouteConfig(
        route_name=route_name,
        chat_models=[m.model_id for m in chat_models],
        embedding_models=[m.model_id for m in embedding_models],
        fallback=[fallback_one, fallback_two],
        rate_limiting=RateLimiting(
            window_size=5,
            max_requests=2,
            max_token=None,
            algorithm=LimitingAlgorithmType.FIXED_WINDOW,
        ),
        token_limiting=TokenLimiting(
            input=Limiting(
                algorithm=LimitingAlgorithmType.FIXED_WINDOW,
                window_size='1 minute',
                max_requests=None,
                max_token=1000,
            ),
            output=Limiting(
                algorithm=LimitingAlgorithmType.FIXED_WINDOW,
                window_size='10 minutes',
                max_requests=None,
                max_token=500,
            ),
        ),
        guardrails=[g.name for g in get_global_guardrails()],
        caching=Caching(enabled=True, ttl=3600, type='exact'),
    )

    return GatewayConfig(
        chat_models=chat_models,
        embedding_models=embedding_models,
        routes={route_name: route},
        guardrails=get_global_guardrails(),
        cache=get_default_cache_config(),
    )


def get_routing_config(name: str = 'keyword-routing') -> DeterministicRoutingConfig:
    return DeterministicRoutingConfig(
        name=name,
        type='deterministic',
        rule=RoutingRuleType.KEYWORD,
        default_model_id='openai',
        output_mapping=[
            OutputMappingEntry(model_id='azure', conditions=['azure', 'gpt']),
        ],
    )


def get_gateway_with_routing(route_name: str = 'rb-gateway') -> GatewayConfig:
    chat_models = get_chat_models()
    embedding_models = get_embedding_models()
    routing_config = get_routing_config()

    route = GatewayRouteConfig(
        route_name=route_name,
        chat_models=[m.model_id for m in chat_models],
        embedding_models=[m.model_id for m in embedding_models],
        routing=routing_config.name,
    )

    return GatewayConfig(
        chat_models=chat_models,
        embedding_models=embedding_models,
        routes={route_name: route},
        routing=[routing_config],
    )


def get_plain_gateway(route_name: str = 'rb-gateway'):
    chat_models = get_chat_models()
    embedding_models = get_embedding_models()

    route = GatewayRouteConfig(
        route_name=route_name,
        chat_models=[m.model_id for m in chat_models],
        embedding_models=[m.model_id for m in embedding_models],
    )

    return GatewayConfig(
        chat_models=chat_models,
        embedding_models=embedding_models,
        routes={route_name: route},
        guardrails=get_global_guardrails(),
        cache=None,
    )


def get_gateway_with_judge_and_semantic_cache(
    route_name: str = 'rb-gateway',
    judge_guardrail_name: str = 'test_judge',
    judge_model_id: str = 'openai',
):
    """Get a gateway config with JUDGE guardrail and semantic caching enabled."""
    chat_models = get_chat_models()
    embedding_models = get_embedding_models()

    # Create JUDGE guardrail
    judge_guardrail = Guardrail(
        name=judge_guardrail_name,
        type=GuardrailType.JUDGE,
        description='Test judge guardrail',
        where=GuardrailWhereType.OUTPUT,
        behavior=GuardrailBehaviorType.BLOCK,
        parameters=JudgeParameter(
            prompt_ref='test_prompt.md',
            model_id=judge_model_id,
        ),
    )

    route = GatewayRouteConfig(
        route_name=route_name,
        chat_models=[m.model_id for m in chat_models],
        embedding_models=[m.model_id for m in embedding_models],
        guardrails=[judge_guardrail_name],
        caching=SemanticCaching(
            enabled=True,
            type='semantic',
            ttl=3600,
            embedding_model_id='text-embedding-3-small',
        ),
    )

    return GatewayConfig(
        chat_models=chat_models,
        embedding_models=embedding_models,
        routes={route_name: route},
        guardrails=[*get_global_guardrails(), judge_guardrail],
        cache=get_default_cache_config(),
    )
