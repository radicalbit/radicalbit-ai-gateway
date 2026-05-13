from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
import pytest

from tests.common.mocked_gateway_config_openai import (
    get_gateway_routing_text_classification,
)

from radicalbit_ai_gateway.routing.text_classification_router import (
    TextClassificationRouter,
)


@pytest.fixture
def text_classification_router():
    config = get_gateway_routing_text_classification()
    routing_config = config.routing_by_name['intent_routing']
    route = config.routes['support_route']
    models_by_id = {mid: config.chat_models_by_id[mid] for mid in route.chat_models}
    return TextClassificationRouter(config=routing_config, models_by_id=models_by_id)


def _make_mock_client(json_response: dict, raise_for_status=None):
    mock_resp = MagicMock()
    mock_resp.json.return_value = json_response
    if raise_for_status:
        mock_resp.raise_for_status.side_effect = raise_for_status
    else:
        mock_resp.raise_for_status.return_value = None

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


class TestTextClassificationRouter:
    async def test_known_class_routes_to_billing_model(
        self, text_classification_router
    ):
        mock_client = _make_mock_client(
            {'predictions': [{'class': 'billing', 'score': 0.95}]}
        )
        with patch('httpx.AsyncClient', return_value=mock_client):
            result = await text_classification_router.select_model(
                [HumanMessage(content='I have a billing issue')]
            )
        assert result.model_id == 'billing_model'

    async def test_known_class_routes_to_billing_model_second_condition(
        self, text_classification_router
    ):
        mock_client = _make_mock_client(
            {'predictions': [{'class': 'invoice', 'score': 0.91}]}
        )
        with patch('httpx.AsyncClient', return_value=mock_client):
            result = await text_classification_router.select_model(
                [HumanMessage(content='I need my invoice')]
            )
        assert result.model_id == 'billing_model'

    async def test_known_class_routes_to_tech_support_model(
        self, text_classification_router
    ):
        mock_client = _make_mock_client(
            {'predictions': [{'class': 'technical', 'score': 0.88}]}
        )
        with patch('httpx.AsyncClient', return_value=mock_client):
            result = await text_classification_router.select_model(
                [HumanMessage(content='The app is crashing')]
            )
        assert result.model_id == 'tech_support_model'

    async def test_known_class_routes_to_tech_support_model_second_condition(
        self, text_classification_router
    ):
        mock_client = _make_mock_client(
            {'predictions': [{'class': 'bug', 'score': 0.83}]}
        )
        with patch('httpx.AsyncClient', return_value=mock_client):
            result = await text_classification_router.select_model(
                [HumanMessage(content='I found a bug')]
            )
        assert result.model_id == 'tech_support_model'

    async def test_unknown_class_returns_default(self, text_classification_router):
        mock_client = _make_mock_client(
            {'predictions': [{'class': 'unknown', 'score': 0.5}]}
        )
        with patch('httpx.AsyncClient', return_value=mock_client):
            result = await text_classification_router.select_model(
                [HumanMessage(content='Hello')]
            )
        assert result.model_id == 'general_queue'

    async def test_http_500_returns_default(self, text_classification_router):
        mock_client = _make_mock_client(
            {},
            raise_for_status=httpx.HTTPStatusError(
                'Server error',
                request=MagicMock(),
                response=MagicMock(status_code=500),
            ),
        )
        with patch('httpx.AsyncClient', return_value=mock_client):
            result = await text_classification_router.select_model(
                [HumanMessage(content='Help me')]
            )
        assert result.model_id == 'general_queue'

    async def test_timeout_returns_default(self, text_classification_router):
        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException('timed out'))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch('httpx.AsyncClient', return_value=mock_client):
            result = await text_classification_router.select_model(
                [HumanMessage(content='Help me')]
            )
        assert result.model_id == 'general_queue'

    async def test_payload_uses_dataframe_records(self, text_classification_router):
        mock_client = _make_mock_client(
            {'predictions': [{'class': 'billing', 'score': 0.95}]}
        )
        with patch('httpx.AsyncClient', return_value=mock_client):
            await text_classification_router.select_model(
                [HumanMessage(content='I have a billing issue')]
            )
        mock_client.post.assert_called_once()
        _, kwargs = mock_client.post.call_args
        assert kwargs['json'] == {
            'dataframe_records': [{'inputs': 'I have a billing issue'}]
        }

    async def test_no_human_message_returns_default(self, text_classification_router):
        with patch('httpx.AsyncClient') as mock_client_cls:
            result = await text_classification_router.select_model([])
        mock_client_cls.assert_not_called()
        assert result.model_id == 'general_queue'

    async def test_only_system_message_returns_default(
        self, text_classification_router
    ):
        with patch('httpx.AsyncClient') as mock_client_cls:
            result = await text_classification_router.select_model(
                [SystemMessage(content='You are a helpful assistant')]
            )
        mock_client_cls.assert_not_called()
        assert result.model_id == 'general_queue'
