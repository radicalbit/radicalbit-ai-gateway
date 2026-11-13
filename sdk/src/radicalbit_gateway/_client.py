"""The client: one ``httpx2.Client`` and the one function that sends a request.

The methods (``gw.<tag>.<action>()``) are generated into ``_resources.py``;
each of them calls ``Gateway._request`` with what the spec says about its
operation.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from typing import Any
from urllib.parse import quote

import httpx2
from pydantic import TypeAdapter
from pydantic_core import to_jsonable_python

from radicalbit_gateway._resources import Resources
from radicalbit_gateway._types import NotGiven
from radicalbit_gateway.errors import error_from_response


@lru_cache
def _adapter(response_type: Any) -> TypeAdapter[Any]:
    return TypeAdapter(response_type)


def _given(values: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The values the caller gave, as JSON-compatible data (aliases for models)."""
    if values is None:
        return None
    given = {k: v for k, v in values.items() if not isinstance(v, NotGiven)}
    return to_jsonable_python(given, by_alias=True)


class Gateway(Resources):
    """A client of the management API of a Radicalbit AI Gateway.

    ``auth`` is any ``httpx2.Auth`` (the hook for authenticated deployments),
    ``transport`` any ``httpx2`` transport (e.g. ``httpx2.MockTransport`` in
    tests), ``headers`` are sent with every request.
    """

    def __init__(
        self,
        base_url: str,
        *,
        auth: httpx2.Auth | None = None,
        timeout: float = 30.0,
        transport: httpx2.BaseTransport | None = None,
        headers: Mapping[str, str] | None = None,
    ):
        self._http = httpx2.Client(
            base_url=base_url.rstrip('/'),
            auth=auth,
            timeout=timeout,
            transport=transport,
            headers=headers,
        )
        super().__init__(self)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Gateway:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        path_params: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        files: Mapping[str, Any] | None = None,
        response: Any = None,
    ) -> Any:
        """Send one request; the parsed 2xx body as ``response``, or a typed error.

        Arguments left ``NOT_GIVEN`` are not sent. ``files`` go to httpx2 as they are.
        """
        segments = _given(path_params) or {}
        url = path.format(**{k: quote(str(v), safe='') for k, v in segments.items()})
        files = {k: v for k, v in (files or {}).items() if not isinstance(v, NotGiven)}
        reply = self._http.request(
            method,
            url,
            params=_given(query),
            json=_given(json),
            data=_given(data),
            files=files or None,
        )
        if not reply.is_success:
            raise error_from_response(reply.status_code, reply.content)
        if response is None:
            return None
        return _adapter(response).validate_json(reply.content)
