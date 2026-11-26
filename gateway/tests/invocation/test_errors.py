from google.genai import errors as genai_errors

from radicalbit_ai_gateway.invocation.errors import upstream_refusal
from radicalbit_ai_gateway.llm.errors import provider_status


def test_a_gemini_error_without_message_falls_back_to_its_description():
    error = genai_errors.ClientError(400, {'error': {'code': 400}})

    assert provider_status(error) == (400, str(error), {'error': {'code': 400}})
    refusal = upstream_refusal(error)
    assert refusal is not None
    assert refusal.client_message == str(error)


def test_a_gemini_error_with_a_message_keeps_it():
    error = genai_errors.ClientError(
        404, {'error': {'code': 404, 'message': 'model not found'}}
    )

    assert provider_status(error) == (
        404,
        'model not found',
        {'error': {'code': 404, 'message': 'model not found'}},
    )


def test_a_gemini_error_without_a_json_body_gets_one():
    error = genai_errors.ServerError(503, None)

    assert provider_status(error) == (
        503,
        str(error),
        {'error': {'message': str(error)}},
    )
