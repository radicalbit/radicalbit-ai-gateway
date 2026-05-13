from decimal import Decimal

from radicalbit_ai_gateway.models.caching import CacheConfig, Caching
from radicalbit_ai_gateway.models.credentials import Credentials
from radicalbit_ai_gateway.models.fallback import Fallback, FallbackModelType
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.guardrails import (
    Guardrail,
    GuardrailBehaviorType,
    GuardrailType,
    GuardrailWhereType,
)
from radicalbit_ai_gateway.models.limiting import (
    BudgetLimiting,
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
    SemanticRoutingConfig,
    TextClassificationRoutingConfig,
)


def get_default_fallbacks() -> list[Fallback]:
    return [
        Fallback(
            target='openai-o4-mini',
            fallbacks=['openai-o3', 'openai-o1-mini'],
            type=FallbackModelType.CHAT,
        ),
        Fallback(
            target='openai-o3',
            fallbacks=['openai-o1-mini', 'openai-o4-mini'],
            type=FallbackModelType.CHAT,
        ),
        Fallback(
            target='text-embedding-3-small',
            fallbacks=['text-embedding-ada-002'],
            type=FallbackModelType.EMBEDDING,
        ),
    ]


def make_chat_model(
    model_id: str,
    model: str,
    temperature: float,
    max_tokens: int,
    seed: int | None = None,
) -> Model:
    return Model(
        model_id=model_id,
        model=model,
        credentials=Credentials(api_key='sk-123'),
        params={
            'temperature': temperature,
            'max_tokens': max_tokens,
            'seed': seed,
            'top_p': 0.9,
            'logprobs': None,
            'top_logprobs': None,
        },
        retry_attempts=3,
    )


def make_embedding_model(model_id: str, model: str) -> Model:
    return Model(
        model_id=model_id,
        model=model,
        credentials=Credentials(api_key='sk-123'),
    )


def _openai_guardrails() -> list[Guardrail]:
    return [
        Guardrail(
            name='starts_with_check',
            type=GuardrailType.STARTS_WITH,
            where=GuardrailWhereType.INPUT,
            behavior=GuardrailBehaviorType.WARN,
            parameters={'values': ['buonasera']},
        ),
        Guardrail(
            name='keyword_block',
            type=GuardrailType.CONTAINS,
            where=GuardrailWhereType.INPUT,
            behavior=GuardrailBehaviorType.BLOCK,
            parameters={'values': ['ciao']},
        ),
        Guardrail(
            name='email_address_redaction',
            type=GuardrailType.REGEX,
            where=GuardrailWhereType.OUTPUT,
            behavior=GuardrailBehaviorType.BLOCK,
            parameters={
                'values': [r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z|a-z]{2,}\b']
            },
            response_message='Email addresses are not allowed.',
        ),
        Guardrail(
            name='uuid_block',
            type=GuardrailType.REGEX,
            where=GuardrailWhereType.INPUT,
            behavior=GuardrailBehaviorType.BLOCK,
            parameters={
                'values': [
                    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-5][0-9a-f]{3}-[089ab][0-9a-f]{3}-[0-9a-f]{12}$'
                ]
            },
            response_message='Specific UUID format detected and blocked.',
        ),
    ]


def _openai_route_guardrail_names() -> list[str]:
    return [
        'starts_with_check',
        'keyword_block',
        'email_address_redaction',
        'uuid_block',
    ]


def get_gateway_openai_with_guardrails() -> GatewayConfig:

    chat_models = [
        make_chat_model(
            'openai-o4-mini', 'openai/gpt-4o-mini', temperature=0.9, max_tokens=150
        ),
        make_chat_model(
            'openai-o3-mini', 'openai/o3-mini', temperature=0.9, max_tokens=150
        ),
    ]
    embedding_models = [
        make_embedding_model('text-embedding-3-small', 'openai/text-embedding-3-small'),
    ]
    guardrails = _openai_guardrails()
    route = GatewayRouteConfig(
        route_name='rb-gateway',
        chat_models=[m.model_id for m in chat_models],
        embedding_models=[m.model_id for m in embedding_models],
        guardrails=_openai_route_guardrail_names(),
    )
    return GatewayConfig(
        chat_models=chat_models,
        embedding_models=embedding_models,
        routes={'rb-gateway': route},
        guardrails=guardrails,
    )


def get_gateway_openai_cached() -> GatewayConfig:

    chat_models = [
        make_chat_model(
            'openai-o4-mini', 'openai/gpt-4o-mini', temperature=0.9, max_tokens=150
        ),
        make_chat_model(
            'openai-o3-mini', 'openai/o3-mini', temperature=0.9, max_tokens=150
        ),
    ]
    guardrails = _openai_guardrails()
    route = GatewayRouteConfig(
        route_name='rb-gateway',
        chat_models=[m.model_id for m in chat_models],
        guardrails=_openai_route_guardrail_names(),
        caching=Caching(enabled=True, ttl=120, type='exact'),
    )
    return GatewayConfig(
        chat_models=chat_models,
        routes={'rb-gateway': route},
        guardrails=guardrails,
        cache=CacheConfig(redis_host='localhost', redis_port=6379),
    )


def get_gateway_embedded_cached() -> GatewayConfig:

    chat_models = [
        make_chat_model(
            'openai-o4-mini', 'openai/gpt-4o-mini', temperature=0.9, max_tokens=150
        ),
    ]
    embedding_models = [
        make_embedding_model('text-embedding-3-small', 'openai/text-embedding-3-small'),
    ]
    route = GatewayRouteConfig(
        route_name='rb-gateway',
        chat_models=[m.model_id for m in chat_models],
        embedding_models=[m.model_id for m in embedding_models],
        caching=Caching(enabled=True, ttl=120, type='exact'),
    )
    return GatewayConfig(
        chat_models=chat_models,
        embedding_models=embedding_models,
        routes={'rb-gateway': route},
        cache=CacheConfig(redis_host='localhost', redis_port=6379),
    )


def get_gateway_embedded_limiting() -> GatewayConfig:

    chat_models = [
        make_chat_model(
            'openai-o4-mini', 'openai/gpt-4o-mini', temperature=0.9, max_tokens=150
        ),
    ]
    embedding_models = [
        Model(
            model_id='text-embedding-3-small',
            model='openai/text-embedding-3-small',
            credentials=Credentials(api_key='sk-123'),
            input_cost_per_million_tokens=Decimal('0.25'),
        ),
    ]
    route = GatewayRouteConfig(
        route_name='rb-gateway',
        chat_models=[m.model_id for m in chat_models],
        embedding_models=[m.model_id for m in embedding_models],
        token_limiting=TokenLimiting(
            input=Limiting(
                algorithm=LimitingAlgorithmType.FIXED_WINDOW,
                window_size='10 seconds',
                max_token=5,
            ),
        ),
        budget_limiting=BudgetLimiting(
            algorithm=LimitingAlgorithmType.FIXED_WINDOW,
            window_size='10 seconds',
            max_budget=10,
        ),
    )
    return GatewayConfig(
        chat_models=chat_models,
        embedding_models=embedding_models,
        routes={'rb-gateway': route},
    )


def get_gateway_ollama_no_api_key() -> GatewayConfig:

    chat_models = [
        Model(
            model_id='qwen',
            model='openai/qwen2.5:3b',
            credentials=Credentials(
                base_url='http://host.docker.internal:11434/v1',
            ),
            params={'temperature': 0.7, 'top_p': 0.9},
            prompt='You are an helpful assistant and you are nice to the customer that you are facing. Do not take initiatives',
            role='system',
        ),
    ]
    route = GatewayRouteConfig(
        route_name='rb-gateway',
        chat_models=['qwen'],
    )
    return GatewayConfig(
        chat_models=chat_models,
        routes={'rb-gateway': route},
    )


def _make_model(model_id: str, model: str) -> Model:
    return Model(
        model_id=model_id,
        model=model,
        credentials=Credentials(api_key='sk-dummy'),
    )


def get_gateway_routing_keyword() -> GatewayConfig:

    chat_models = [
        _make_model('billing_model', 'openai/gpt-4o'),
        _make_model('tech_support_model', 'openai/gpt-4o-mini'),
        _make_model('general_queue', 'openai/gpt-4o'),
    ]
    routing = DeterministicRoutingConfig(
        name='keyword_routing',
        type='deterministic',
        default_model_id='general_queue',
        rule=RoutingRuleType.KEYWORD,
        output_mapping=[
            OutputMappingEntry(
                model_id='billing_model', conditions=['billing', 'invoice', 'payment']
            ),
            OutputMappingEntry(
                model_id='tech_support_model', conditions=['error', 'bug']
            ),
        ],
    )
    route = GatewayRouteConfig(
        route_name='support_route',
        chat_models=[m.model_id for m in chat_models],
        routing=routing.name,
    )
    return GatewayConfig(
        chat_models=chat_models,
        routes={'support_route': route},
        routing=[routing],
    )


def get_gateway_routing_context_length() -> GatewayConfig:

    chat_models = [
        _make_model('gpt-4o', 'openai/gpt-4o'),
        _make_model('gpt-4o-mini', 'openai/gpt-4o-mini'),
        _make_model('gpt-4.1', 'openai/gpt-4.1'),
    ]
    routing = DeterministicRoutingConfig(
        name='context_routing',
        type='deterministic',
        default_model_id='gpt-4o',
        rule=RoutingRuleType.CONTEXT_LENGTH,
        output_mapping=[
            OutputMappingEntry(model_id='gpt-4o-mini', conditions={'gte': 200}),
            OutputMappingEntry(model_id='gpt-4.1', conditions={'gte': 400}),
        ],
    )
    route = GatewayRouteConfig(
        route_name='smart_route',
        chat_models=[m.model_id for m in chat_models],
        routing=routing.name,
    )
    return GatewayConfig(
        chat_models=chat_models,
        routes={'smart_route': route},
        routing=[routing],
    )


def get_gateway_routing_time() -> GatewayConfig:

    chat_models = [
        _make_model('weekday_model', 'openai/gpt-4o'),
        _make_model('night_model', 'openai/gpt-4o-mini'),
        _make_model('default_model', 'openai/gpt-4o'),
    ]
    routing = DeterministicRoutingConfig(
        name='time_routing',
        type='deterministic',
        default_model_id='default_model',
        rule=RoutingRuleType.TIME,
        output_mapping=[
            OutputMappingEntry(model_id='weekday_model', conditions=['* 9-17 * * 1-5']),
            OutputMappingEntry(
                model_id='night_model', conditions=['* 0-8 * * *', '* 18-23 * * *']
            ),
        ],
    )
    route = GatewayRouteConfig(
        route_name='time_route',
        chat_models=[m.model_id for m in chat_models],
        routing=routing.name,
    )
    return GatewayConfig(
        chat_models=chat_models,
        routes={'time_route': route},
        routing=[routing],
    )


def get_gateway_routing_token_length() -> GatewayConfig:

    chat_models = [
        _make_model('gpt-4o', 'openai/gpt-4o'),
        _make_model('gpt-4o-mini', 'openai/gpt-4o-mini'),
        _make_model('gpt-4.1', 'openai/gpt-4.1'),
    ]
    routing = DeterministicRoutingConfig(
        name='token_routing',
        type='deterministic',
        default_model_id='gpt-4o',
        rule=RoutingRuleType.TOKEN_LENGTH,
        output_mapping=[
            OutputMappingEntry(model_id='gpt-4o-mini', conditions={'lte': 199}),
            OutputMappingEntry(model_id='gpt-4.1', conditions={'between': [200, 799]}),
        ],
    )
    route = GatewayRouteConfig(
        route_name='smart_route',
        chat_models=[m.model_id for m in chat_models],
        routing=routing.name,
    )
    return GatewayConfig(
        chat_models=chat_models,
        routes={'smart_route': route},
        routing=[routing],
    )


def get_gateway_routing_text_classification() -> GatewayConfig:

    chat_models = [
        _make_model('billing_model', 'openai/gpt-4o'),
        _make_model('tech_support_model', 'openai/gpt-4o-mini'),
        _make_model('general_queue', 'openai/gpt-3.5-turbo'),
    ]
    routing = TextClassificationRoutingConfig(
        name='intent_routing',
        type='text_classification',
        default_model_id='general_queue',
        url='http://text-classifier:8888',
        output_mapping=[
            OutputMappingEntry(
                model_id='billing_model', conditions=['billing', 'invoice']
            ),
            OutputMappingEntry(
                model_id='tech_support_model', conditions=['technical', 'bug']
            ),
        ],
    )
    route = GatewayRouteConfig(
        route_name='support_route',
        chat_models=[m.model_id for m in chat_models],
        routing=routing.name,
    )
    return GatewayConfig(
        chat_models=chat_models,
        routes={'support_route': route},
        routing=[routing],
    )


def get_gateway_routing_semantic() -> GatewayConfig:
    chat_models = [
        _make_model('code_model', 'openai/gpt-4o'),
        _make_model('general_model', 'openai/gpt-4o-mini'),
        _make_model('default_model', 'openai/gpt-3.5-turbo'),
    ]
    embedding_models = [
        make_embedding_model('embedder', 'openai/text-embedding-ada-002'),
    ]
    routing = SemanticRoutingConfig(
        name='semantic_routing',
        type='semantic',
        default_model_id='default_model',
        embedding_model_id='embedder',
        similarity_threshold=0.7,
        output_mapping=[
            OutputMappingEntry(
                model_id='code_model',
                conditions=[
                    'write a python function',
                    'debug this code',
                    'explain this algorithm',
                ],
            ),
            OutputMappingEntry(
                model_id='general_model',
                conditions=[
                    'what is the weather',
                    'tell me a joke',
                    'summarize this article',
                ],
            ),
        ],
    )
    route = GatewayRouteConfig(
        route_name='smart_route',
        chat_models=[m.model_id for m in chat_models],
        embedding_models=[m.model_id for m in embedding_models],
        routing=routing.name,
    )
    return GatewayConfig(
        chat_models=chat_models,
        embedding_models=embedding_models,
        routes={'smart_route': route},
        routing=[routing],
    )


def get_gateway_dashboard_test_config() -> GatewayConfig:
    chat_models = [
        Model(
            model_id='openai',
            model='openai/gpt-4o',
            credentials=Credentials(api_key='sk-dummy-key'),
            params={'temperature': 0.9},
            prompt='Always answer in Italian',
            role='system',
        ),
        Model(
            model_id='llama3',
            model='openai/llama3',
            credentials=Credentials(base_url='http://localhost:11434/v1'),
            params={'temperature': 0.7, 'top_p': 0.9},
            prompt='You are a helpful assistant.',
            role='system',
        ),
        Model(
            model_id='qwen',
            model='openai/Qwen/Qwen2.5-1.5B-Instruct',
            credentials=Credentials(base_url='http://localhost:54989/v1'),
            prompt='You are a helpful assistant.',
            role='system',
        ),
        Model(
            model_id='qwen2.5:3b',
            model='openai/qwen2.5:3b',
            credentials=Credentials(base_url='http://localhost:11434/v1'),
            params={'temperature': 0.7, 'top_p': 0.9},
            prompt='Answer in italian.',
            role='system',
        ),
    ]
    embedding_models = [
        Model(
            model_id='text-embedding-3-small',
            model='openai/text-embedding-3-small',
            credentials=Credentials(api_key='sk-dummy-key'),
        ),
        Model(
            model_id='text-embedding-ada-002',
            model='openai/text-embedding-ada-002',
            credentials=Credentials(api_key='sk-dummy-key'),
        ),
    ]
    guardrails = [
        Guardrail(
            name='starts_with_check',
            type=GuardrailType.STARTS_WITH,
            where=GuardrailWhereType.INPUT,
            behavior=GuardrailBehaviorType.WARN,
            parameters={'values': ['ciao', 'buonasera']},
        ),
        Guardrail(
            name='keyword_block',
            type=GuardrailType.CONTAINS,
            where=GuardrailWhereType.OUTPUT,
            behavior=GuardrailBehaviorType.BLOCK,
            parameters={'values': ['ciao']},
        ),
        Guardrail(
            name='email_address_redaction',
            type=GuardrailType.REGEX,
            where=GuardrailWhereType.IO,
            behavior=GuardrailBehaviorType.BLOCK,
            parameters={
                'values': [r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b']
            },
            response_message='Email addresses are not allowed.',
        ),
        Guardrail(
            name='uuid_block',
            type=GuardrailType.REGEX,
            where=GuardrailWhereType.INPUT,
            behavior=GuardrailBehaviorType.BLOCK,
            parameters={
                'values': [
                    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-5][0-9a-f]{3}-[089ab][0-9a-f]{3}-[0-9a-f]{12}$'
                ]
            },
            response_message='Specific UUID format detected and blocked.',
        ),
    ]
    rb_gateway_route = GatewayRouteConfig(
        route_name='rb-gateway',
        chat_models=['openai', 'llama3', 'qwen'],
        embedding_models=['text-embedding-3-small', 'text-embedding-ada-002'],
        guardrails=[
            'starts_with_check',
            'keyword_block',
            'email_address_redaction',
            'uuid_block',
        ],
        rate_limiting=RateLimiting(
            algorithm=LimitingAlgorithmType.FIXED_WINDOW,
            window_size='1 minute',
            max_requests=20,
        ),
        token_limiting=TokenLimiting(
            input=Limiting(
                algorithm=LimitingAlgorithmType.FIXED_WINDOW,
                window_size='1 minute',
                max_token=1000,
            ),
            output=Limiting(
                algorithm=LimitingAlgorithmType.FIXED_WINDOW,
                window_size='10 minutes',
                max_token=500,
            ),
        ),
        caching=Caching(enabled=True, ttl=300, type='exact'),
        fallback=[
            Fallback(
                target='openai',
                fallbacks=['llama3', 'qwen'],
                type=FallbackModelType.CHAT,
            ),
            Fallback(
                target='llama3',
                fallbacks=['openai', 'qwen'],
                type=FallbackModelType.CHAT,
            ),
            Fallback(
                target='text-embedding-3-small',
                fallbacks=['text-embedding-ada-002'],
                type=FallbackModelType.EMBEDDING,
            ),
        ],
    )
    rb_gateway_two_route = GatewayRouteConfig(
        route_name='rb-gateway-two',
        chat_models=['qwen2.5:3b'],
        rate_limiting=RateLimiting(
            algorithm=LimitingAlgorithmType.FIXED_WINDOW,
            window_size='10 minutes',
            max_requests=3,
        ),
    )
    return GatewayConfig(
        chat_models=chat_models,
        embedding_models=embedding_models,
        routes={'rb-gateway': rb_gateway_route, 'rb-gateway-two': rb_gateway_two_route},
        guardrails=guardrails,
        cache=CacheConfig(redis_host='localhost', redis_port=6379),
    )


def get_default_gateway_openai() -> GatewayConfig:
    chat_models = [
        make_chat_model(
            'openai-o4-mini', 'openai/gpt-o4-mini', temperature=0.9, max_tokens=150
        ),
        make_chat_model(
            'openai-o3', 'openai/gpt-o3', temperature=0.7, max_tokens=20, seed=12
        ),
        make_chat_model(
            'openai-o1-mini', 'openai/gpt-o1-mini', temperature=0.7, max_tokens=1000
        ),
    ]

    embedding_models = [
        make_embedding_model('text-embedding-3-small', 'openai/text-embedding-3-small'),
        make_embedding_model('text-embedding-ada-002', 'openai/text-embedding-ada-002'),
    ]

    routes = {
        'rb-gateway': GatewayRouteConfig(
            route_name='rb-gateway',
            chat_models=['openai-o4-mini', 'openai-o3', 'openai-o1-mini'],
            embedding_models=['text-embedding-3-small', 'text-embedding-ada-002'],
            fallback=get_default_fallbacks(),
        )
    }

    return GatewayConfig(
        routes=routes,
        chat_models=chat_models,
        embedding_models=embedding_models,
        guardrails=[],
        cache=None,
    )
