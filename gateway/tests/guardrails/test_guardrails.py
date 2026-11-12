import copy
from unittest.mock import MagicMock, patch

from azure.identity import ClientSecretCredential, EnvironmentCredential
from presidio_analyzer import EntityRecognizer
import pytest

from tests.common.db_mock import API_KEY_UUID, GROUP_UUID, REQUEST_UUID
from tests.common.guardrails import apply_check, apply_redact
from tests.common.mocked_gateway_config_openai import get_default_gateway_openai

from radicalbit_ai_gateway.guardrails.guardrails import Guardrails
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.llm.messages import AIMessage, HumanMessage
from radicalbit_ai_gateway.models.guardrails import (
    AhdsParams,
    CheckParameter,
    Guardrail,
    GuardrailBehaviorType,
    GuardrailMessageRole,
    GuardrailType,
    GuardrailWhereType,
    RedactParameter,
)
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.exceptions import GuardrailBadRequest

BLOCK = GuardrailBehaviorType.BLOCK
WARN = GuardrailBehaviorType.WARN
SOFT_BLOCK = GuardrailBehaviorType.SOFT_BLOCK
INPUT = GuardrailWhereType.INPUT
OUTPUT = GuardrailWhereType.OUTPUT
IO = GuardrailWhereType.IO
T = GuardrailType

IBAN = 'IT60X0542811101000000123456'
EMAIL = 'test@radicalbit.io'


def _guardrail(name, kind, behavior, where, values=None, entities=None, **extra):
    parameters = (
        CheckParameter(values=values)
        if values is not None
        else RedactParameter(language='it', entities=entities)
    )
    return Guardrail(
        name=name,
        type=kind,
        behavior=behavior,
        where=where,
        parameters=parameters,
        **extra,
    )


BLOCKING = [
    _guardrail('block_start_with_hello', T.STARTS_WITH, BLOCK, INPUT, ['Hello', 'Ciao']),
    _guardrail('warn_end_with_world', T.ENDS_WITH, WARN, OUTPUT, ['World']),
    _guardrail('block_contains_sensitive', T.CONTAINS, BLOCK, IO, ['sensitive']),
    _guardrail('warn_regex_digits', T.REGEX, WARN, IO, [r'\d+']),
    _guardrail('check_italian_iban', T.PRESIDIO_ANALYZER, BLOCK, INPUT, entities=['IBAN_CODE']),
]  # fmt: skip

SOFT_BLOCKING = [
    _guardrail('soft_block_start_with_hello', T.STARTS_WITH, SOFT_BLOCK, INPUT, ['Hello', 'Ciao']),
    _guardrail('soft_block_contains_sensitive', T.CONTAINS, SOFT_BLOCK, OUTPUT, ['sensitive']),
    _guardrail('soft_block_regex_digits', T.REGEX, SOFT_BLOCK, IO, [r'\d+']),
]  # fmt: skip


@pytest.fixture(autouse=True)
def redact_events():
    with (
        patch('radicalbit_ai_gateway.guardrails.guardrail_check.emit_event'),
        patch('radicalbit_ai_gateway.guardrails.guardrail_redact.emit_event') as emit,
    ):
        yield emit


def _project(guardrails):
    return Guardrails(
        presidio_engine=PresidioEngine(),
        judge_engine=JudgeEngine(prompt_manager=MagicMock(spec_set=PromptManager)),
        cost_service=MagicMock(spec_set=CostService),
        guardrails=guardrails,
    )


def _route(guardrails):
    route_config = copy.deepcopy(get_default_gateway_openai().routes['rb-gateway'])
    route_config.guardrails = [g.name for g in guardrails]
    return route_config


IDENTITY = {
    'request_uuid': str(REQUEST_UUID),
    'api_key_uuid': str(API_KEY_UUID),
    'group_uuid': str(GROUP_UUID),
    'api_key_name': 'fake-name',
    'group_name': 'test-group',
}


async def _check(guardrails, content, where):
    return await apply_check(
        _project(guardrails),
        route_config=_route(guardrails),
        messages=[HumanMessage(content=content)],
        where=where,
        **IDENTITY,
    )


async def _redact(guardrails, messages, where):
    return await apply_redact(
        _project(guardrails),
        route_config=_route(guardrails),
        messages=messages,
        where=where,
        **IDENTITY,
    )


@pytest.mark.parametrize(
    ('content', 'where', 'name', 'kind'),
    [
        ('Hello there', INPUT, 'block_start_with_hello', 'STARTS_WITH'),
        ('Ciao come stai?', INPUT, 'block_start_with_hello', 'STARTS_WITH'),
        ('This contains sensitive info', INPUT, 'block_contains_sensitive', 'CONTAINS'),
        ('This has sensitive data', OUTPUT, 'block_contains_sensitive', 'CONTAINS'),
        (f'This is my IBAN {IBAN}', INPUT, 'check_italian_iban', 'PRESIDIO_ANALYZER'),
    ],
    ids=[
        'starts_with',
        'starts_with_second_value',
        'io_input',
        'io_output',
        'presidio',
    ],
)
async def test_a_block_guardrail_raises_naming_itself(content, where, name, kind):
    with pytest.raises(GuardrailBadRequest) as exc_info:
        await _check(BLOCKING, content, where)

    message = str(exc_info.value)
    for tag in (
        '[GUARDRAIL TRIGGERED]',
        '[route=rb-gateway]',
        f'[where={where.name}]',
        f'[name={name}]',
        f'[type={kind}]',
        '[behavior=BLOCK]',
    ):
        assert tag in message
    assert exc_info.value.guardrail.name == name


@pytest.mark.parametrize(
    ('content', 'where', 'name'),
    [
        ('A normal message', INPUT, None),
        ('Hello there', OUTPUT, None),
        ('Hello there', INPUT, 'soft_block_start_with_hello'),
        ('This contains sensitive data', OUTPUT, 'soft_block_contains_sensitive'),
        ('Text with 123 numbers', INPUT, 'soft_block_regex_digits'),
        ('Response with 456 numbers', OUTPUT, 'soft_block_regex_digits'),
    ],
    ids=['no_match', 'wrong_phase', 'input', 'output', 'io_input', 'io_output'],
)
async def test_a_soft_block_answers_for_the_phase_it_matched(content, where, name):
    soft_block = (await _check(SOFT_BLOCKING, content, where)).soft_block

    if name is None:
        assert soft_block is None
        return
    assert soft_block.guardrail.name == name
    assert soft_block.where == where
    expected = (
        'I cannot process this request as it violates content policy'
        if where == INPUT
        else 'This response has been blocked due to policy violation'
    )
    assert soft_block.get_soft_block_message() == f'{expected}: {name}'


async def test_a_soft_block_is_logged(caplog):
    with caplog.at_level('INFO', logger='radicalbit-ai-gateway'):
        await _check(SOFT_BLOCKING, 'Hello there', INPUT)

    assert '[where=INPUT]' in caplog.text
    assert '[name=soft_block_start_with_hello]' in caplog.text


async def test_a_soft_block_listed_first_wins_over_a_block():
    mixed = [
        _guardrail('soft_hello', T.STARTS_WITH, SOFT_BLOCK, INPUT, ['Hello']),
        _guardrail('block_hello', T.CONTAINS, BLOCK, INPUT, ['Hello']),
    ]

    soft_block = (await _check(mixed, 'Hello there', INPUT)).soft_block

    assert soft_block.guardrail.name == 'soft_hello'


@pytest.mark.parametrize(
    ('guardrails', 'content', 'where'),
    [
        (BLOCKING, 'Hello!', OUTPUT),
        ([_guardrail('empty', T.CONTAINS, BLOCK, INPUT, [])], 'anything', INPUT),
        ([_guardrail('pii', T.PRESIDIO_ANALYZER, BLOCK, INPUT, entities=['IBAN_CODE'])], '   ', INPUT),
        (
            [
                _guardrail(
                    'assistant_only', T.CONTAINS, BLOCK, INPUT, ['Hello'],
                    message_roles=[GuardrailMessageRole.ASSISTANT],
                )
            ],
            'Hello',
            INPUT,
        ),
    ],
    ids=['input_only_on_output', 'no_values', 'blank_text', 'no_message_selected'],
)  # fmt: skip
async def test_a_check_with_nothing_to_match_lets_the_message_through(
    guardrails, content, where
):
    result = await _check(guardrails, content, where)

    assert result.soft_block is None
    assert not result.warned


async def test_a_presidio_check_that_fails_to_analyze_does_not_block():
    guardrail = _guardrail(
        'pii', T.PRESIDIO_ANALYZER, BLOCK, INPUT, entities=['IBAN_CODE']
    )

    with patch.object(PresidioEngine, 'get_analyzer', side_effect=RuntimeError('down')):
        result = await _check([guardrail], f'IBAN {IBAN}', INPUT)

    assert result.soft_block is None


def _anonymizer(where, entities, **extra):
    return _guardrail(
        'redact', T.PRESIDIO_ANONYMIZER, BLOCK, where, entities=entities, **extra
    )


@pytest.mark.parametrize(
    ('where', 'entities', 'content', 'expected'),
    [
        (INPUT, ['IBAN_CODE'], f'Here it is: {IBAN}', 'Here it is: <IBAN_CODE>'),
        (OUTPUT, ['EMAIL_ADDRESS'], f'My email {EMAIL}', 'My email <EMAIL_ADDRESS>'),
        (
            INPUT,
            ['IBAN_CODE', 'EMAIL_ADDRESS'],
            f'Email {EMAIL} and IBAN {IBAN}',
            'Email <EMAIL_ADDRESS> and IBAN <IBAN_CODE>',
        ),
        (INPUT, ['EMAIL_ADDRESS'], '', ''),
        (
            INPUT,
            ['EMAIL_ADDRESS'],
            [
                {'type': 'text', 'text': f'mail {EMAIL}'},
                {'type': 'text', 'text': ''},
                {'type': 'text'},
                {'type': 'image_url', 'image_url': {'url': 'https://x/a.png'}},
                'raw',
            ],
            [
                {'type': 'text', 'text': 'mail <EMAIL_ADDRESS>'},
                {'type': 'text', 'text': ''},
                {'type': 'text'},
                {'type': 'image_url', 'image_url': {'url': 'https://x/a.png'}},
                'raw',
            ],
        ),
    ],
    ids=['iban_input', 'email_output', 'both', 'empty_text', 'only_text_parts'],
)
async def test_an_anonymizer_redacts_the_entities_it_names(
    redact_events, where, entities, content, expected
):
    [redacted] = await _redact(
        [_anonymizer(where, entities)], [HumanMessage(content=content)], where
    )

    assert redacted.content == expected
    assert redact_events.called == (content != expected)


async def test_an_anonymizer_that_selects_no_message_returns_them_as_they_are():
    guardrail = _anonymizer(
        INPUT, ['EMAIL_ADDRESS'], message_roles=[GuardrailMessageRole.USER]
    )
    messages = [AIMessage(content=f'mail {EMAIL}')]

    assert await _redact([guardrail], messages, INPUT) == messages


@pytest.mark.parametrize(
    ('analyzer', 'error'),
    [
        ({'side_effect': RuntimeError('no model')}, RuntimeError),
        (
            {
                'return_value': MagicMock(
                    **{'analyze.side_effect': ValueError('entity')}
                )
            },
            ValueError,
        ),
    ],
    ids=['analyzer_init', 'unsupported_entity'],
)
async def test_an_anonymizer_failure_is_raised(analyzer, error):
    with (
        patch.object(PresidioEngine, 'get_analyzer', **analyzer),
        pytest.raises(error),
    ):
        await _redact(
            [_anonymizer(INPUT, ['EMAIL_ADDRESS'])],
            [HumanMessage(content=f'mail {EMAIL}')],
            INPUT,
        )


class TestAhdsIntegration:
    """Tests for the Azure Health Data Services de-identification recognizer integration."""

    def test_local_analyzer_has_no_ahds_recognizer(self):
        engine = PresidioEngine()
        analyzer = engine.get_analyzer('local')
        recognizer_names = [r.name for r in analyzer.registry.recognizers]
        assert 'Azure Health Deid' not in ' '.join(recognizer_names)

    def test_ahds_analyzer_raises_when_endpoint_missing(self):
        engine = PresidioEngine()
        with pytest.raises(ValueError, match='AHDS endpoint must be set'):
            engine.get_analyzer('ahds')

    def test_ahds_analyzer_registers_recognizer(self):
        mock_recognizer_instance = MagicMock(spec=EntityRecognizer)
        mock_recognizer_instance.name = 'Azure Health Deid'
        mock_recognizer_instance.supported_language = 'en'
        mock_recognizer_instance.supported_entities = ['PATIENT', 'DOCTOR']
        mock_recognizer_instance.get_supported_entities.return_value = [
            'PATIENT',
            'DOCTOR',
        ]

        with (
            patch(
                'radicalbit_ai_gateway.guardrails.presidio.AzureHealthDeidRecognizer',
                return_value=mock_recognizer_instance,
            ) as mock_cls,
            patch.object(
                PresidioEngine,
                '_build_ahds_client',
                return_value=MagicMock(),
            ) as mock_build_client,
        ):
            engine = PresidioEngine()
            engine.get_analyzer(
                'ahds', AhdsParams(endpoint='https://test.api.deid.azure.com')
            )
            mock_cls.assert_called_once()
            mock_build_client.assert_called_once_with(
                'https://test.api.deid.azure.com', '2024-11-15', None, None, None
            )

    @pytest.mark.parametrize(
        ('secret', 'expected'),
        [
            (('tenant-123', 'client-456', 'super-secret'), ClientSecretCredential),
            ((None, None, None), EnvironmentCredential),
        ],
        ids=['client_secret', 'environment'],
    )
    def test_credential_uses_the_client_secret_or_the_environment(
        self, secret, expected
    ):
        assert isinstance(PresidioEngine._build_ahds_credential(*secret), expected)

    def test_resolve_settings_from_ahds_params(self):
        engine = PresidioEngine()
        ahds = AhdsParams(
            endpoint='https://guardrail.deid.azure.com',
            tenant_id='gr-tenant',
            client_secret='super-secret',
        )
        endpoint, api_version, tenant_id, client_id, secret = (
            engine._resolve_ahds_settings(ahds)
        )
        # All settings come from the per-guardrail AhdsParams;
        # api_version falls back to the model default.
        assert endpoint == 'https://guardrail.deid.azure.com'
        assert tenant_id == 'gr-tenant'
        assert client_id is None
        assert api_version == '2024-11-15'
        # The SecretStr is unwrapped to a plain string for the Azure credential.
        assert secret == 'super-secret'
        # And it is masked in the model's repr/serialization.
        assert 'super-secret' not in repr(ahds)
