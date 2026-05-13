import asyncio
import unittest
from unittest.mock import MagicMock

from langchain_core.messages import AIMessageChunk
import pytest

from radicalbit_ai_gateway.invocation.chat_model_invoker import ChatModelInvoker
from radicalbit_ai_gateway.models.fallback import Fallback
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.utils.exceptions import ModelInvokerInternalError


class TestStreamingFallback(unittest.TestCase):
    def setUp(self):
        # Primary Model (will fail)
        self.mock_model = MagicMock(spec=Model)
        self.mock_model.model = 'openai/gpt-4'
        self.mock_model.model_id = 'gpt-4'
        self.mock_model.params = {}
        self.mock_model.credentials = None

        # Fallback Model (will succeed)
        self.mock_fb_model = MagicMock(spec=Model)
        self.mock_fb_model.model = 'anthropic/claude-3'
        self.mock_fb_model.model_id = 'claude-3'
        self.mock_fb_model.params = {}
        self.mock_fb_model.credentials = None

        self.mock_cost_service = MagicMock()

        # Fallback setup
        self.mock_chat_model = MagicMock()  # Primary chat model
        self.mock_fb_chat_model = MagicMock()  # Fallback chat model

        # Fallback definition
        fallback = Fallback(model_id='gpt-4', target='gpt-4', fallbacks=['claude-3'])

        # We need to manually set up the model_map because we are mocking init_chat_model
        # But ChatModelInvoker._initialize_models does complex logic.
        # Instead, we will force the model_map populated after init.

        with unittest.mock.patch(
            'radicalbit_ai_gateway.invocation.chat_model_invoker.init_chat_model'
        ) as mock_init:
            # We can't easily distinguish calls here, so we'll just patch the instance manually later
            mock_init.return_value = self.mock_chat_model

            self.invoker = ChatModelInvoker(
                models=[self.mock_model, self.mock_fb_model],
                cost_service=self.mock_cost_service,
                fallbacks=[fallback],
            )

        # Manual Override of model_map to inject our mocks
        # Structure: model_id -> (Model, BaseChatModel, list[(Model, BaseChatModel)])

        # Fallback list for primary
        fb_list = [(self.mock_fb_model, self.mock_fb_chat_model)]

        self.invoker.model_map = {
            'gpt-4': (self.mock_model, self.mock_chat_model, fb_list),
            'claude-3': (self.mock_fb_model, self.mock_fb_chat_model, []),
        }

        self.invoker._record_metrics = MagicMock()

    def test_streaming_fallback_success(self):
        async def run_test():
            # Primary fails immediately
            self.mock_chat_model.astream = MagicMock(
                side_effect=Exception('Primary Failure')
            )

            # Fallback succeeds
            async def mock_fb_stream(*args, **kwargs):
                yield AIMessageChunk(
                    content='Fallback Response',
                    usage_metadata={
                        'input_tokens': 50,
                        'output_tokens': 20,
                        'total_tokens': 70,
                    },
                )

            self.mock_fb_chat_model.astream = MagicMock(side_effect=mock_fb_stream)

            return [
                chunk
                async for chunk in self.invoker.stream(
                    request_uuid='req-1',
                    api_key_uuid='key-1',
                    group_uuid='group-1',
                    api_key_name='key-name',
                    group_name='group-name',
                    route_name='route-1',
                    messages=[],
                    model_id='gpt-4',
                    tools=None,
                    tool_choice=None,
                    hashed_api_key='hash',
                )
            ]

        chunks = asyncio.run(run_test())

        # Verify we got chunks from fallback
        assert len(chunks) > 0
        assert chunks[0].content == 'Fallback Response'

        # Verify metrics recorded correctly
        self.invoker._record_metrics.assert_called_once()
        call_args = self.invoker._record_metrics.call_args[1]

        assert call_args['target_model_id'] == 'gpt-4'  # Target was primary
        assert call_args['model'].model_id == 'claude-3'  # Actual invoked was fallback
        assert call_args['fallback_triggered'] is True
        assert call_args['token_input_count'] == 50
        assert call_args['token_output_count'] == 20

    def test_streaming_all_fail(self):
        async def run_test():
            # Primary fails
            self.mock_chat_model.astream = MagicMock(
                side_effect=Exception('Primary Failure')
            )
            # Fallback fails
            self.mock_fb_chat_model.astream = MagicMock(
                side_effect=Exception('Fallback Failure')
            )

            with pytest.raises(ModelInvokerInternalError):
                async for _ in self.invoker.stream(
                    request_uuid='req-2',
                    api_key_uuid='key-2',
                    group_uuid='group-2',
                    api_key_name='key-name',
                    group_name='group-name',
                    route_name='route-2',
                    messages=[],
                    model_id='gpt-4',
                    tools=None,
                    tool_choice=None,
                    hashed_api_key='hash',
                ):
                    pass

        asyncio.run(run_test())

        # Metrics should still be recorded (latency/failure)
        self.invoker._record_metrics.assert_called_once()
        call_args = self.invoker._record_metrics.call_args[1]
        assert (
            call_args['fallback_triggered'] is False
        )  # technically fallback didn't succeed? logic says triggered=fallback_triggered variable which is False initially


if __name__ == '__main__':
    unittest.main()
