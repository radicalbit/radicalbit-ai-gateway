from radicalbit_ai_gateway.models.gateway_config import GatewayConfig


def test_route_name_injection_from_dict():
    raw_data = {
        'chat_models': [
            {'model_id': 'prod_model', 'model': 'openai/gpt-4o'},
            {'model_id': 'staging_model', 'model': 'openai/gpt-4o-mini'},
        ],
        'embedding_models': [],
        'routes': {
            'production_route': {'chat_models': ['prod_model']},
            'staging_route': {'chat_models': ['staging_model']},
        },
    }

    gateway_config = GatewayConfig(**raw_data)

    assert len(gateway_config.routes) == 2
    assert gateway_config.routes['production_route'].route_name == 'production_route'
    assert gateway_config.routes['staging_route'].route_name == 'staging_route'

    assert gateway_config.routes['production_route'].chat_models == ['prod_model']
    assert gateway_config.routes['staging_route'].chat_models == ['staging_model']

    by_id = {m.model_id: m for m in gateway_config.chat_models}
    assert by_id['prod_model'].model == 'openai/gpt-4o'
    assert by_id['staging_model'].model == 'openai/gpt-4o-mini'
