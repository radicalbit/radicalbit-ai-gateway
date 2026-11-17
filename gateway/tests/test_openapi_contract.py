"""The operation ids are the SDK's method and module names: they must be unique
and only change on purpose (the SDK is regenerated from them).
"""

from collections import Counter
from importlib.metadata import PackageNotFoundError
import warnings

from fastapi import FastAPI
import pytest

from radicalbit_ai_gateway import server
from radicalbit_ai_gateway.sdk_spec import build_sdk_spec
from radicalbit_ai_gateway.server import app


def _operation_ids(spec: dict) -> list[str]:
    return [
        operation['operationId']
        for path in spec['paths'].values()
        for operation in path.values()
    ]


def test_every_operation_id_is_unique():
    app.openapi_schema = None
    with warnings.catch_warnings():
        # FastAPI warns on a duplicate operation id
        warnings.filterwarnings('error', message='Duplicate Operation ID')
        spec = app.openapi()
    duplicates = [i for i, n in Counter(_operation_ids(spec)).items() if n > 1]
    assert duplicates == []


def test_sdk_operations_document_their_errors():
    spec = build_sdk_spec(app)
    for path in spec['paths'].values():
        for operation in path.values():
            assert operation.get('description'), operation['operationId']
            assert any(s.startswith('4') for s in operation['responses'])


def test_sdk_spec_refuses_an_app_without_the_sdk_operations():
    with pytest.raises(ValueError, match='SDK operations not found'):
        build_sdk_spec(FastAPI())


def test_the_spec_version_falls_back_when_the_package_is_not_installed(
    monkeypatch,
):
    def not_installed(name):
        raise PackageNotFoundError(name)

    monkeypatch.setattr(server, 'package_version', not_installed)
    assert server._gateway_version() == '0.1.0'
