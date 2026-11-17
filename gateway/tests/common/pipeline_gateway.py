"""The project the request-path tests serve: a route for every endpoint and
policy, and the canned replies of its model gpt-a. The golden scenarios of
``tests/endpoints/cross_endpoint/test_pipeline_golden.py`` run on it.
"""

from tests.common import provider_responses as upstream
from tests.common.provider_recorder import CannedResponse

CREDENTIALS = {'api_key': 'sk-test'}


def priced(model_id: str, name: str) -> dict:
    """Return a model priced at 1 per million input tokens, 2 per million output."""
    return {
        'model_id': model_id,
        'model': name,
        'credentials': CREDENTIALS,
        'input_cost_per_million_tokens': 1,
        'output_cost_per_million_tokens': 2,
    }


def contains_guardrail(name: str, where: str, behavior: str, value: str) -> dict:
    """Return a ``contains`` guardrail on ``value``."""
    return {
        'name': name,
        'type': 'contains',
        'where': where,
        'behavior': behavior,
        'parameters': {'values': [value]},
    }


INPUT_GUARDRAILS = ['warn_in', 'judge', 'soft_in']
INPUT_LIMIT = {'input': {'window_size': '1 minute', 'max_token': 3}}
ROOMY_LIMIT = {'input': {'window_size': '1 minute', 'max_token': 1000}}

CONFIG = {
    'chat_models': [
        priced('a', 'openai/gpt-a'),
        priced('b', 'openai/gpt-b'),
        priced('j1', 'openai/gpt-j1'),
        priced('r1', 'openai/gpt-r1'),
    ],
    'embedding_models': [priced('e1', 'openai/text-embedding-3-small')],
    'transcription_models': [priced('t1', 'openai/gpt-4o-transcribe')],
    'decision_models': [
        {
            'model_id': 'd1',
            'model': 'typesafe/jev-latest',
            'credentials': {'api_key': 'ts-test'},
            'input_cost_per_million_tokens': 3,
        }
    ],
    'guardrails': [
        contains_guardrail('warn_in', 'input', 'warn', 'warnme'),
        contains_guardrail('soft_in', 'input', 'soft_block', 'softme'),
        contains_guardrail('soft_out', 'output', 'soft_block', 'softout'),
        contains_guardrail('block_out', 'output', 'block', 'blockout'),
        {
            'name': 'judge',
            'type': 'judge',
            'where': 'input',
            'behavior': 'block',
            'parameters': {'model_id': 'j1', 'prompt': 'Judge this.'},
        },
    ],
    'routing': [
        {
            'name': 'by-llm',
            'type': 'llm',
            'router_model_id': 'r1',
            'default_model_id': 'a',
            'output_mapping': [
                {'model_id': 'a', 'description': 'Questions about geography'},
                {'model_id': 'b', 'description': 'Questions about code'},
            ],
        }
    ],
    'routes': {
        'chat': {
            'chat_models': ['a', 'b'],
            'routing': 'by-llm',
            'guardrails': INPUT_GUARDRAILS,
        },
        'limited': {
            'chat_models': ['a', 'b'],
            'routing': 'by-llm',
            'guardrails': INPUT_GUARDRAILS,
            'token_limiting': INPUT_LIMIT,
        },
        'output': {
            'chat_models': ['a'],
            'guardrails': ['warn_in', 'soft_in', 'soft_out'],
        },
        'embed': {'embedding_models': ['e1'], 'guardrails': ['warn_in', 'soft_in']},
        'embed_limited': {'embedding_models': ['e1'], 'token_limiting': INPUT_LIMIT},
        'audio': {'transcription_models': ['t1']},
        'audio_limited': {
            'transcription_models': ['t1'],
            'duration_limiting': {
                'window_size': '1 minute',
                'max_duration_seconds': 1,
            },
        },
        'agent': {'decision_models': ['d1'], 'guardrails': ['warn_in', 'soft_in']},
        # Limits that let every request through: their checks show in traces.
        'chat_metered': {'chat_models': ['a'], 'token_limiting': ROOMY_LIMIT},
        'embed_metered': {'embedding_models': ['e1'], 'token_limiting': ROOMY_LIMIT},
        'audio_metered': {
            'transcription_models': ['t1'],
            'duration_limiting': {
                'window_size': '1 minute',
                'max_duration_seconds': 60,
            },
        },
        'agent_metered': {'decision_models': ['d1'], 'token_limiting': ROOMY_LIMIT},
        'output_metered': {
            'chat_models': ['a'],
            'guardrails': ['soft_out', 'block_out'],
            'token_limiting': ROOMY_LIMIT,
        },
    },
}


def gpt_a_completion(text: str = 'Paris is in France') -> CannedResponse:
    """Return gpt-a's reply, as OpenAI sends it."""
    return upstream.openai_completion(
        text, model='gpt-a', prompt_tokens=11, completion_tokens=5
    )


def gpt_a_stream(*parts: str) -> CannedResponse:
    """Return gpt-a's reply, as OpenAI streams it."""
    return upstream.openai_stream(
        list(parts or ('Paris', ' is in France')),
        model='gpt-a',
        prompt_tokens=11,
        completion_tokens=5,
    )
