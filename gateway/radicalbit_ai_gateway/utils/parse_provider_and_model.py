from radicalbit_ai_gateway.utils.exceptions import ModelInvokerBadRequest


def parse_provider_and_model(model_str: str) -> tuple[str, str]:
    if '/' not in model_str:
        raise ModelInvokerBadRequest(f'Invalid model string: {model_str}')
    provider, model = model_str.split('/', 1)
    if not provider or not model:
        raise ModelInvokerBadRequest(
            f'Provider and model names cannot be empty, got: {model_str}'
        )
    return provider, model
