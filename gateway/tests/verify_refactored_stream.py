import asyncio
import unittest
from unittest.mock import MagicMock

from langchain_core.messages import AIMessageChunk

from radicalbit_ai_gateway.invocation.chat_model_invoker import ChatModelInvoker
from radicalbit_ai_gateway.models.model import Model


class TestRefactoredStream(unittest.TestCase):
    def setUp(self):
        self.mock_model = MagicMock(spec=Model)
        self.mock_model.model = 'openai/gpt-4'
        self.mock_model.model_id = 'gpt-4'
        self.mock_model.params = {}
        self.mock_model.credentials = None

        self.mock_cost_service = MagicMock()

        with unittest.mock.patch(
            'radicalbit_ai_gateway.invocation.chat_model_invoker.init_chat_model'
        ) as mock_init:
            self.mock_chat_model = MagicMock()
            mock_init.return_value = self.mock_chat_model

            self.invoker = ChatModelInvoker(
                models=[self.mock_model],
                cost_service=self.mock_cost_service,
                fallbacks=None,
            )

        self.invoker._record_metrics = MagicMock()

    def test_stream_helper_metrics(self):
        async def run_test():
            # Mock astream to yield chunks
            async def mock_stream(*args, **kwargs):
                # Chunk 1: Input tokens + cached (new format)
                yield AIMessageChunk(
                    content='',
                    usage_metadata={
                        'input_tokens': 100,
                        'output_tokens': 0,
                        'total_tokens': 100,
                        'input_token_details': {'cache_read': 25},
                    },
                )
                # Chunk 2: Output tokens
                yield AIMessageChunk(
                    content='',
                    usage_metadata={
                        'input_tokens': 0,
                        'output_tokens': 50,
                        'total_tokens': 50,
                    },
                )

            self.mock_chat_model.astream = MagicMock(side_effect=mock_stream)

            stats = {
                'token_input_count': 0,
                'token_output_count': 0,
                'cached_token_count': 0,
            }

            async for _ in self.invoker._stream_with_metrics(
                self.mock_chat_model, [], stats
            ):
                pass

            return stats

        stats = asyncio.run(run_test())

        # Verify stats are updated correctly
        assert stats['cached_token_count'] == 25
        # Input tokens shoud be 100 - 25 = 75 (logic inside helper)
        assert stats['token_input_count'] == 75
        assert stats['token_output_count'] == 50

    def test_full_stream_flow(self):
        async def run_test():
            async def mock_stream(*args, **kwargs):
                yield AIMessageChunk(
                    content='Hello',
                    usage_metadata={
                        'input_tokens': 100,
                        'output_tokens': 10,
                        'total_tokens': 110,
                    },
                )

            self.mock_chat_model.astream = MagicMock(side_effect=mock_stream)

            async for _ in self.invoker.stream(
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
            ):
                pass

        asyncio.run(run_test())

        self.invoker._record_metrics.assert_called_once()
        call_args = self.invoker._record_metrics.call_args[1]
        assert call_args['token_input_count'] == 100
        assert call_args['token_output_count'] == 10


if __name__ == '__main__':
    unittest.main()
