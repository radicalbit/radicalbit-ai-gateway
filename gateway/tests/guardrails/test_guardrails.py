import copy
import unittest
from unittest.mock import MagicMock, patch

from azure.identity import ClientSecretCredential, EnvironmentCredential
from langchain_core.messages import HumanMessage
from presidio_analyzer import EntityRecognizer
import pytest

from tests.common.db_mock import API_KEY_UUID, GROUP_UUID, REQUEST_UUID
from tests.common.mocked_gateway_config_openai import get_default_gateway_openai

from radicalbit_ai_gateway.guardrails.guardrail_engine import GuardrailEngine
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.models.guardrails import (
    AhdsParams,
    CheckParameter,
    Guardrail,
    GuardrailBehaviorType,
    GuardrailType,
    GuardrailWhereType,
    RedactParameter,
)
from radicalbit_ai_gateway.models.soft_block_info import SoftBlockInfo
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import GuardrailBadRequest


# Arrange
@pytest.fixture
def guardrail_engine():
    cost_service = MagicMock(spec_set=CostService)
    prompt_manager = MagicMock(spec_set=PromptManager)
    return GuardrailEngine(
        presidio_engine=PresidioEngine(),
        judge_engine=JudgeEngine(prompt_manager=prompt_manager),
        cost_service=cost_service,
    )


gateway_config = get_default_gateway_openai()

mock_guardrails_check = [
    Guardrail(
        name='block_start_with_hello',
        type=GuardrailType.STARTS_WITH,
        behavior=GuardrailBehaviorType.BLOCK,
        where=GuardrailWhereType.INPUT,
        parameters=CheckParameter(values=['Hello', 'Ciao']),
    ),
    Guardrail(
        name='warn_end_with_world',
        type=GuardrailType.ENDS_WITH,
        behavior=GuardrailBehaviorType.WARN,
        where=GuardrailWhereType.OUTPUT,
        parameters=CheckParameter(values=['World']),
    ),
    Guardrail(
        name='block_contains_sensitive',
        type=GuardrailType.CONTAINS,
        behavior=GuardrailBehaviorType.BLOCK,
        where=GuardrailWhereType.IO,
        parameters=CheckParameter(values=['sensitive']),
    ),
    Guardrail(
        name='warn_regex_digits',
        type=GuardrailType.REGEX,
        behavior=GuardrailBehaviorType.WARN,
        where=GuardrailWhereType.IO,
        parameters=CheckParameter(values=[r'\d+']),
    ),
    Guardrail(
        name='check_italian_iban',
        type=GuardrailType.PRESIDIO_ANALYZER,
        behavior=GuardrailBehaviorType.BLOCK,
        where=GuardrailWhereType.INPUT,
        parameters=RedactParameter(language='it', entities=['IBAN_CODE']),
    ),
]

route_config_check = copy.deepcopy(gateway_config.routes['rb-gateway'])
route_config_check.guardrails = [g.name for g in mock_guardrails_check]

mock_soft_block_guardrails = [
    Guardrail(
        name='soft_block_start_with_hello',
        type=GuardrailType.STARTS_WITH,
        behavior=GuardrailBehaviorType.SOFT_BLOCK,
        where=GuardrailWhereType.INPUT,
        parameters=CheckParameter(values=['Hello', 'Ciao']),
    ),
    Guardrail(
        name='soft_block_contains_sensitive',
        type=GuardrailType.CONTAINS,
        behavior=GuardrailBehaviorType.SOFT_BLOCK,
        where=GuardrailWhereType.OUTPUT,
        parameters=CheckParameter(values=['sensitive']),
    ),
    Guardrail(
        name='soft_block_regex_digits',
        type=GuardrailType.REGEX,
        behavior=GuardrailBehaviorType.SOFT_BLOCK,
        where=GuardrailWhereType.IO,
        parameters=CheckParameter(values=[r'\d+']),
    ),
]

route_config_soft_block = copy.deepcopy(gateway_config.routes['rb-gateway'])
route_config_soft_block.guardrails = [g.name for g in mock_soft_block_guardrails]


class TestGuardrail(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.cost_service: CostService = MagicMock(spec_set=CostService)
        cls.prompt_manager: PromptManager = MagicMock(spec_set=PromptManager)
        cls.guardrail_engine = GuardrailEngine(
            presidio_engine=PresidioEngine(),
            judge_engine=JudgeEngine(prompt_manager=cls.prompt_manager),
            cost_service=cls.cost_service,
            guardrails=mock_guardrails_check + mock_soft_block_guardrails,
        )
        cls.guardrail_check = cls.guardrail_engine.guardrail_check
        cls.guardrail_redact = cls.guardrail_engine.guardrail_redact
        cls.emit_event_patcher = patch(
            'radicalbit_ai_gateway.guardrails.guardrail_check.emit_event',
            autospec=True,
        )
        cls.emit_event_patcher.start()
        cls.emit_event_patcher_redact = patch(
            'radicalbit_ai_gateway.guardrails.guardrail_redact.emit_event',
            autospec=True,
        )
        cls.emit_event_patcher_redact.start()

    @classmethod
    def tearDownClass(cls):
        cls.emit_event_patcher.stop()
        cls.emit_event_patcher_redact.stop()

    @pytest.mark.asyncio
    async def test_apply_guardrails_no_trigger(self):
        await self.guardrail_engine.guardrail_check.apply_guardrails(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='fake-name',
            messages=[HumanMessage(content='A normal message')],
            route_config=route_config_soft_block,
            where=GuardrailWhereType.INPUT,
            group_name='test-group',
        )

    @pytest.mark.asyncio
    async def test_block_guardrail_triggered(self):
        with pytest.raises(GuardrailBadRequest) as exc_info:
            await self.guardrail_engine.guardrail_check.apply_guardrails(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                messages=[HumanMessage(content='Hello there')],
                route_config=route_config_check,
                where=GuardrailWhereType.INPUT,
                group_name='test-group',
            )
        msg = str(exc_info.value)
        assert '[GUARDRAIL TRIGGERED]' in msg
        assert '[route=rb-gateway]' in msg
        assert '[where=INPUT]' in msg
        assert '[name=block_start_with_hello]' in msg
        assert '[type=STARTS_WITH]' in msg
        assert '[behavior=BLOCK]' in msg
        assert exc_info.value.guardrail.name == 'block_start_with_hello'

        with pytest.raises(GuardrailBadRequest) as exc_info:
            await self.guardrail_engine.guardrail_check.apply_guardrails(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                messages=[HumanMessage(content='Ciao come stai?')],
                route_config=route_config_check,
                where=GuardrailWhereType.INPUT,
                group_name='test-group',
            )
        msg = str(exc_info.value)
        assert '[GUARDRAIL TRIGGERED]' in msg
        assert '[route=rb-gateway]' in msg
        assert '[where=INPUT]' in msg
        assert '[name=block_start_with_hello]' in msg
        assert '[type=STARTS_WITH]' in msg
        assert '[behavior=BLOCK]' in msg
        assert exc_info.value.guardrail.name == 'block_start_with_hello'

    @pytest.mark.asyncio
    async def test_start_with_hello_not_triggered_if_output(self):
        await self.guardrail_engine.guardrail_check.apply_guardrails(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='fake-name',
            messages=[HumanMessage(content='Hello!')],
            route_config=route_config_check,
            where=GuardrailWhereType.OUTPUT,
            group_name='test-group',
        )

    @pytest.mark.asyncio
    async def test_io_guardrail_evaluated_input(self):
        with pytest.raises(GuardrailBadRequest) as exc_info:
            await self.guardrail_engine.guardrail_check.apply_guardrails(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                messages=[HumanMessage(content='This contains sensitive info')],
                route_config=route_config_check,
                where=GuardrailWhereType.INPUT,
                group_name='test-group',
            )

        msg = str(exc_info.value)
        assert '[GUARDRAIL TRIGGERED]' in msg
        assert '[route=rb-gateway]' in msg
        assert '[where=INPUT]' in msg
        assert '[name=block_contains_sensitive]' in msg
        assert '[type=CONTAINS]' in msg
        assert '[behavior=BLOCK]' in msg

        assert exc_info.value.guardrail.name == 'block_contains_sensitive'

    @pytest.mark.asyncio
    async def test_io_guardrail_evaluated_output(self):
        with pytest.raises(GuardrailBadRequest) as err:
            await self.guardrail_engine.guardrail_check.apply_guardrails(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                messages=[HumanMessage(content='This output has sensitive data')],
                route_config=route_config_check,
                where=GuardrailWhereType.OUTPUT,
                group_name='test-group',
            )

        msg = str(err.value)
        assert '[GUARDRAIL TRIGGERED]' in msg
        assert '[route=rb-gateway]' in msg
        assert '[where=OUTPUT]' in msg
        assert '[name=block_contains_sensitive]' in msg
        assert '[type=CONTAINS]' in msg
        assert '[behavior=BLOCK]' in msg

        assert err.value.guardrail.name == 'block_contains_sensitive'

    @pytest.mark.asyncio
    async def test_block_iban_triggered(self):
        with pytest.raises(GuardrailBadRequest) as exc_info:
            await self.guardrail_engine.guardrail_check.apply_guardrails(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                messages=[
                    HumanMessage(content='This is my IBAN IT60X0542811101000000123456')
                ],
                route_config=route_config_check,
                where=GuardrailWhereType.INPUT,
                group_name='test-group',
            )

        msg = str(exc_info.value)
        assert '[GUARDRAIL TRIGGERED]' in msg
        assert '[route=rb-gateway]' in msg
        assert '[where=INPUT]' in msg
        assert '[name=check_italian_iban]' in msg
        assert '[behavior=BLOCK]' in msg
        assert '[type=PRESIDIO_ANALYZER]' in msg
        assert exc_info.value.guardrail.name == 'check_italian_iban'

    @pytest.mark.asyncio
    async def test_redact_input_iban_triggered(self):
        presidio_guardrail = Guardrail(
            name='redact_iban',
            type=GuardrailType.PRESIDIO_ANONYMIZER,
            behavior=GuardrailBehaviorType.BLOCK,
            where=GuardrailWhereType.INPUT,
            parameters=RedactParameter(language='it', entities=['IBAN_CODE']),
        )
        route_config_presidio = copy.deepcopy(gateway_config.routes['rb-gateway'])
        route_config_presidio.guardrails = [presidio_guardrail.name]

        guardrail_engine = GuardrailEngine(
            presidio_engine=PresidioEngine(),
            judge_engine=JudgeEngine(prompt_manager=self.prompt_manager),
            cost_service=self.cost_service,
            guardrails=[presidio_guardrail],
        )

        redacted_message = await guardrail_engine.guardrail_redact.apply_guardrails(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='fake-name',
            route_config=route_config_presidio,
            messages=[
                HumanMessage(content='Yes sure here it is: IT60X0542811101000000123456')
            ],
            where=GuardrailWhereType.INPUT,
            group_name='test-group',
        )

        assert redacted_message[0].content == 'Yes sure here it is: <IBAN_CODE>'

    @pytest.mark.asyncio
    async def test_redact_output_email_triggered(self):
        presidio_guardrail = Guardrail(
            name='redact_email',
            type=GuardrailType.PRESIDIO_ANONYMIZER,
            behavior=GuardrailBehaviorType.BLOCK,
            where=GuardrailWhereType.OUTPUT,
            parameters=RedactParameter(language='it', entities=['EMAIL_ADDRESS']),
        )

        route_config_presidio = copy.deepcopy(gateway_config.routes['rb-gateway'])
        route_config_presidio.guardrails = [presidio_guardrail.name]

        guardrail_engine = GuardrailEngine(
            presidio_engine=PresidioEngine(),
            judge_engine=JudgeEngine(prompt_manager=self.prompt_manager),
            cost_service=self.cost_service,
            guardrails=[presidio_guardrail],
        )

        redacted_message = await guardrail_engine.guardrail_redact.apply_guardrails(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='fake-name',
            route_config=route_config_presidio,
            messages=[HumanMessage(content='This is my email test@radicalbit.io')],
            where=GuardrailWhereType.OUTPUT,
            group_name='test-group',
        )

        assert redacted_message[0].content == 'This is my email <EMAIL_ADDRESS>'

    @pytest.mark.asyncio
    async def test_redact_iban_and_email_triggered(self):
        presidio_guardrail = Guardrail(
            name='redact_email',
            type=GuardrailType.PRESIDIO_ANONYMIZER,
            behavior=GuardrailBehaviorType.BLOCK,
            where=GuardrailWhereType.INPUT,
            parameters=RedactParameter(
                language='it', entities=['IBAN_CODE', 'EMAIL_ADDRESS']
            ),
        )
        route_config_presidio = copy.deepcopy(gateway_config.routes['rb-gateway'])
        route_config_presidio.guardrails = [presidio_guardrail.name]

        guardrail_engine = GuardrailEngine(
            presidio_engine=PresidioEngine(),
            judge_engine=JudgeEngine(prompt_manager=self.prompt_manager),
            cost_service=self.cost_service,
            guardrails=[presidio_guardrail],
        )

        redacted_message = await guardrail_engine.guardrail_redact.apply_guardrails(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='fake-name',
            route_config=route_config_presidio,
            messages=[
                HumanMessage(
                    content='This is my email test@radicalbit.io and this is my IBAN IT60X0542811101000000123456'
                )
            ],
            where=GuardrailWhereType.INPUT,
            group_name='test-group',
        )

        assert (
            redacted_message[0].content
            == 'This is my email <EMAIL_ADDRESS> and this is my IBAN <IBAN_CODE>'
        )

    @pytest.mark.asyncio
    async def test_soft_block_input_guardrail_triggered(self):
        """Test that SOFT_BLOCK guardrail returns SoftBlockInfo for input."""
        self.soft_block_info = (
            await self.guardrail_engine.guardrail_check.apply_guardrails(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                messages=[HumanMessage(content='Hello there')],
                route_config=route_config_soft_block,
                where=GuardrailWhereType.INPUT,
                group_name='test-group',
            )
        )

        assert self.soft_block_info is not None
        assert isinstance(self.soft_block_info, SoftBlockInfo)
        assert self.soft_block_info.guardrail.name == 'soft_block_start_with_hello'
        assert self.soft_block_info.where == GuardrailWhereType.INPUT
        assert (
            self.soft_block_info.get_soft_block_message()
            == 'I cannot process this request as it violates content policy: soft_block_start_with_hello'
        )

    @pytest.mark.asyncio
    async def test_soft_block_output_guardrail_triggered(self):
        """Test that SOFT_BLOCK guardrail returns SoftBlockInfo for output."""
        self.soft_block_info = (
            await self.guardrail_engine.guardrail_check.apply_guardrails(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                messages=[HumanMessage(content='This contains sensitive data')],
                route_config=route_config_soft_block,
                where=GuardrailWhereType.OUTPUT,
                group_name='test-group',
            )
        )

        assert self.soft_block_info is not None
        assert isinstance(self.soft_block_info, SoftBlockInfo)
        assert self.soft_block_info.guardrail.name == 'soft_block_contains_sensitive'
        assert self.soft_block_info.where == GuardrailWhereType.OUTPUT
        assert (
            self.soft_block_info.get_soft_block_message()
            == 'This response has been blocked due to policy violation: soft_block_contains_sensitive'
        )

    @pytest.mark.asyncio
    async def test_soft_block_io_guardrail_input(self):
        """Test that SOFT_BLOCK IO guardrail works for input."""
        self.soft_block_info = (
            await self.guardrail_engine.guardrail_check.apply_guardrails(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                messages=[HumanMessage(content='Text with 123 numbers')],
                route_config=route_config_soft_block,
                where=GuardrailWhereType.INPUT,
                group_name='test-group',
            )
        )

        assert self.soft_block_info is not None
        assert isinstance(self.soft_block_info, SoftBlockInfo)
        assert self.soft_block_info.guardrail.name == 'soft_block_regex_digits'
        assert self.soft_block_info.where == GuardrailWhereType.INPUT

    @pytest.mark.asyncio
    async def test_soft_block_io_guardrail_output(self):
        """Test that SOFT_BLOCK IO guardrail works for output."""
        self.soft_block_info = (
            await self.guardrail_engine.guardrail_check.apply_guardrails(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                messages=[HumanMessage(content='Response with 456 numbers')],
                route_config=route_config_soft_block,
                where=GuardrailWhereType.OUTPUT,
                group_name='test-group',
            )
        )

        assert self.soft_block_info is not None
        assert isinstance(self.soft_block_info, SoftBlockInfo)
        assert self.soft_block_info.guardrail.name == 'soft_block_regex_digits'
        assert self.soft_block_info.where == GuardrailWhereType.OUTPUT

    @pytest.mark.asyncio
    async def test_soft_block_not_triggered(self):
        """Test that SOFT_BLOCK guardrail returns None when not triggered."""
        self.soft_block_info = (
            await self.guardrail_engine.guardrail_check.apply_guardrails(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                messages=[HumanMessage(content='Normal message without triggers')],
                route_config=route_config_soft_block,
                where=GuardrailWhereType.INPUT,
                group_name='test-group',
            )
        )

        assert self.soft_block_info is None

    @pytest.mark.asyncio
    async def test_soft_block_wrong_where_not_triggered(self):
        """Test that SOFT_BLOCK guardrail respects where conditions."""
        # INPUT-only guardrail should not trigger on OUTPUT
        self.soft_block_info = (
            await self.guardrail_engine.guardrail_check.apply_guardrails(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                messages=[HumanMessage(content='Hello there')],
                route_config=route_config_soft_block,
                where=GuardrailWhereType.OUTPUT,
                group_name='test-group',
            )
        )

        assert self.soft_block_info is None

    @pytest.mark.asyncio
    async def test_soft_block_logs_info_message(self):
        """Test that SOFT_BLOCK guardrail logs an info message using self.assertLogs."""
        logger_name = 'radicalbit-ai-gateway'
        expected_level = 'INFO'
        with self.assertLogs(logger_name, level=expected_level) as cm:
            await self.guardrail_engine.guardrail_check.apply_guardrails(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                messages=[HumanMessage(content='Hello there')],
                route_config=route_config_soft_block,
                where=GuardrailWhereType.INPUT,
                group_name='test-group',
            )
        log_output = '\n'.join(cm.output)
        guardrail_name = 'soft_block_start_with_hello'
        assert '[where=INPUT]' in log_output
        assert f'[name={guardrail_name}]' in log_output

    @pytest.mark.asyncio
    async def test_mixed_behaviors_soft_block_first(self):
        """Test that when both SOFT_BLOCK and BLOCK guardrails are triggered, SOFT_BLOCK is returned first."""
        mixed_guardrails = [
            Guardrail(
                name='soft_block_start_with_hello',
                type=GuardrailType.STARTS_WITH,
                behavior=GuardrailBehaviorType.SOFT_BLOCK,
                where=GuardrailWhereType.INPUT,
                parameters=CheckParameter(values=['Hello']),
            ),
            Guardrail(
                name='block_contains_hello',
                type=GuardrailType.CONTAINS,
                behavior=GuardrailBehaviorType.BLOCK,
                where=GuardrailWhereType.INPUT,
                parameters=CheckParameter(values=['Hello']),
            ),
        ]

        route_config = copy.deepcopy(gateway_config.routes['rb-gateway'])
        route_config.guardrails = [g.name for g in mixed_guardrails]

        # Should return SoftBlockInfo for the first triggered guardrail (soft block)
        self.soft_block_info = (
            await self.guardrail_engine.guardrail_check.apply_guardrails(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                messages=[HumanMessage(content='Hello there')],
                route_config=route_config,
                where=GuardrailWhereType.INPUT,
                group_name='test-group',
            )
        )

        assert self.soft_block_info is not None
        assert self.soft_block_info.guardrail.name == 'soft_block_start_with_hello'


class TestAhdsIntegration(unittest.IsolatedAsyncioTestCase):
    """Tests for the Azure Health Data Services de-identification recognizer integration."""

    def test_local_analyzer_has_no_ahds_recognizer(self):
        engine = PresidioEngine()
        analyzer = engine.get_analyzer('local')
        recognizer_names = [r.name for r in analyzer.registry.recognizers]
        assert 'Azure Health Deid' not in ' '.join(recognizer_names)

    @patch('radicalbit_ai_gateway.guardrails.presidio.get_app_config')
    def test_ahds_analyzer_raises_when_endpoint_missing(self, mock_get_config):
        real_config = get_app_config()
        mock_config = MagicMock()
        mock_config.log_config.logger_name = real_config.log_config.logger_name
        mock_config.ahds_config.ahds_endpoint = None
        mock_config.ahds_config.ahds_client_secret = None
        mock_get_config.return_value = mock_config

        engine = PresidioEngine()
        with pytest.raises(ValueError, match='AHDS endpoint must be set'):
            engine.get_analyzer('ahds')

    @patch('radicalbit_ai_gateway.guardrails.presidio.get_app_config')
    def test_ahds_analyzer_registers_recognizer(self, mock_get_config):
        real_config = get_app_config()
        mock_config = MagicMock()
        mock_config.log_config.logger_name = real_config.log_config.logger_name
        mock_config.ahds_config.ahds_endpoint = 'https://test.api.deid.azure.com'
        mock_config.ahds_config.ahds_api_version = '2024-11-15'
        mock_config.ahds_config.ahds_tenant_id = None
        mock_config.ahds_config.ahds_client_id = None
        mock_config.ahds_config.ahds_client_secret = None
        mock_get_config.return_value = mock_config

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
            engine.get_analyzer('ahds')
            mock_cls.assert_called_once()
            mock_build_client.assert_called_once_with(
                'https://test.api.deid.azure.com', '2024-11-15', None, None, None
            )

    def test_credential_uses_client_secret_when_configured(self):
        credential = PresidioEngine._build_ahds_credential(
            'tenant-123', 'client-456', 'super-secret'
        )
        assert isinstance(credential, ClientSecretCredential)

    def test_credential_falls_back_to_environment(self):
        credential = PresidioEngine._build_ahds_credential(None, None, None)
        assert isinstance(credential, EnvironmentCredential)

    @patch('radicalbit_ai_gateway.guardrails.presidio.get_app_config')
    def test_ahds_params_override_global(self, mock_get_config):
        mock_config = MagicMock()
        mock_config.ahds_config.ahds_endpoint = 'https://global.deid.azure.com'
        mock_config.ahds_config.ahds_api_version = '2024-11-15'
        mock_config.ahds_config.ahds_tenant_id = 'global-tenant'
        mock_config.ahds_config.ahds_client_id = 'global-client'
        mock_config.ahds_config.ahds_client_secret = None
        mock_get_config.return_value = mock_config

        engine = PresidioEngine()
        ahds = AhdsParams(
            endpoint='https://guardrail.deid.azure.com', tenant_id='gr-tenant'
        )
        endpoint, api_version, tenant_id, client_id, _secret = (
            engine._resolve_ahds_settings(ahds)
        )
        # Per-guardrail values win; unset fields fall back to the global config.
        assert endpoint == 'https://guardrail.deid.azure.com'
        assert tenant_id == 'gr-tenant'
        assert client_id == 'global-client'
        assert api_version == '2024-11-15'
