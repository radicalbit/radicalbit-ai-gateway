"""The web framework's own errors answer in the ErrorOut shape.

Unknown paths, methods not allowed and bodies that cannot be parsed are raised
by FastAPI/Starlette as ``HTTPException``: the gateway's handler answers them
as ``{"error": {...}}``, like every other error of the management API, and
``/v1/messages`` keeps the Messages API shape.
"""

import unittest

from fastapi.testclient import TestClient

from radicalbit_ai_gateway.server import app

PREFIX = '/public/api/v1'


class TestHttpErrorShape(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, raise_server_exceptions=False)

    def test_unknown_path_is_an_error_out(self):
        res = self.client.get(f'{PREFIX}/no-such-resource')
        assert res.status_code == 404
        assert res.json() == {
            'error': {
                'message': 'Not Found',
                'type': 'http_error',
                'param': None,
                'code': 'not_found',
            }
        }

    def test_body_that_cannot_be_parsed_is_an_error_out(self):
        # Not UTF-8: FastAPI cannot decode it, a 400 (invalid JSON is a 422)
        res = self.client.post(
            f'{PREFIX}/configs/validate',
            content=b'\xff',
            headers={'content-type': 'application/json'},
        )
        assert res.status_code == 400
        assert res.json() == {
            'error': {
                'message': 'There was an error parsing the body',
                'type': 'http_error',
                'param': None,
                'code': 'bad_request',
            }
        }

    def test_method_not_allowed_keeps_the_allow_header(self):
        res = self.client.put(f'{PREFIX}/configs/validate', json={})
        assert res.status_code == 405
        assert res.headers['allow'] == 'POST'
        assert res.json()['error']['code'] == 'method_not_allowed'

    def test_invalid_json_is_still_a_request_validation_error(self):
        res = self.client.post(
            f'{PREFIX}/configs/validate',
            content=b'{bad',
            headers={'content-type': 'application/json'},
        )
        assert res.status_code == 422
        assert res.json()['detail'][0]['type'] == 'json_invalid'

    def test_messages_path_keeps_the_messages_api_shape(self):
        res = self.client.post(
            '/v1/messages',
            content=b'\xff',
            headers={'content-type': 'application/json'},
        )
        assert res.status_code == 400
        assert res.json() == {
            'type': 'error',
            'error': {
                'type': 'invalid_request_error',
                'message': 'There was an error parsing the body',
            },
        }
