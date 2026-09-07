"""Regression test for the RequestValidationError handler.

A pydantic model_validator(mode='after') that raises a plain ValueError (the
documented, idiomatic way to fail cross-field validation) puts the raw
exception object in the `ctx.error` key of exc.errors(). Passing that
straight to json.dumps crashes with a 500 instead of returning the intended
422. Reproduced here via CredentialLimitsIn (models/credential_limiting.py),
whose own model_validator raises ValueError on a duplicate limit in the same
batch — first found while running an end-to-end test through docker.
"""

import unittest

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from radicalbit_ai_gateway.models.credential_limiting import CredentialLimitsIn
from radicalbit_ai_gateway.server import validation_exception_handler


class TestValidationExceptionHandler(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app = FastAPI()
        app.add_exception_handler(RequestValidationError, validation_exception_handler)

        @app.post('/limits')
        def _create_limits(limits_in: CredentialLimitsIn):
            return limits_in.model_dump()

        cls.client = TestClient(app)

    def test_model_validator_value_error_returns_422_not_500(self):
        res = self.client.post(
            '/limits',
            json={
                'limits': [
                    {'category': 'budget', 'windowSize': '1 day', 'value': 10},
                    {'category': 'budget', 'windowSize': '1 day', 'value': 20},
                ],
            },
        )
        assert res.status_code == 422
        assert 'Duplicate limit in request' in res.text
