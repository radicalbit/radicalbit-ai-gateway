from radicalbit_ai_gateway.models.gateway_config import GatewayConfig


def resolve_route_models(gateway_config: GatewayConfig, route_name: str):
    route_cfg = gateway_config.routes[route_name]

    chat_by_id = {m.model_id: m for m in (gateway_config.chat_models or [])}
    emb_by_id = {m.model_id: m for m in (gateway_config.embedding_models or [])}

    chat_models = [chat_by_id[mid] for mid in (route_cfg.chat_models or [])]

    embedding_ids = route_cfg.embedding_models or []
    embedding_models = (
        [emb_by_id[mid] for mid in embedding_ids] if embedding_ids else None
    )

    return route_cfg, chat_models, embedding_models
