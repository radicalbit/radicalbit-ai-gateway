"""The operation ids are the SDK's method and module names: they must be unique
and only change on purpose (the SDK is regenerated from them).
"""

from collections import Counter
import warnings

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
