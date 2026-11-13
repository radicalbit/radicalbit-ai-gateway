"""The clients: ``Gateway`` (sync) and ``AsyncGateway``, and how a request is sent.

The methods (``gw.<tag>.<action>()``) are generated into ``_resources.py``;
each of them calls ``_request`` with what the spec says about its operation.
Everything else a request goes through is here, shared by both clients:
building it, retrying it, turning the answer into a model or a typed error.

Retries: a failed call is sent again, up to ``max_retries`` times, only when
sending it twice cannot do the work twice:

- any method, when the request never reached the gateway (connection
  refused, connect timeout) or the gateway refused it unprocessed (429, 503);
- reads only (GET, HEAD, OPTIONS), when the answer was lost or the gateway
  failed midway (other timeouts, a broken connection, 408, 500, 502, 504).
  Anything else (POST, PATCH, DELETE) is not sent again then: it may have
  happened, and the second attempt would fail (a 409, a 404) on work already
  done, or do it twice.

The wait doubles from 0.5 s up to 8 s, with jitter, or follows the gateway's
``Retry-After`` (at most 60 s). A multipart upload is retried only when its
files are bytes: an open file would be sent again from where the first
attempt stopped reading.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
import email.utils
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
import os
import random
import time
from typing import Any, Self
from urllib.parse import quote

import httpx2
from pydantic import TypeAdapter
from pydantic_core import to_jsonable_python

from radicalbit_gateway._resources import AsyncResources, Resources
from radicalbit_gateway._types import NOT_GIVEN, NotGiven
from radicalbit_gateway.errors import (
    APIConnectionError,
    APITimeoutError,
    error_from_response,
)

BASE_URL_ENV = 'RADICALBIT_GATEWAY_BASE_URL'
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 2

_RETRY_ANY_METHOD = frozenset({429, 503})
_RETRY_IDEMPOTENT = frozenset({408, 500, 502, 504})
_IDEMPOTENT_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS'})
# The request never left: no risk in sending it again
_NOT_SENT = (httpx2.ConnectError, httpx2.ConnectTimeout, httpx2.PoolTimeout)
_FIRST_WAIT, _MAX_WAIT, _MAX_RETRY_AFTER = 0.5, 8.0, 60.0

# Looked up at call time, so tests can skip the waits
_sleep = time.sleep
_async_sleep = asyncio.sleep


def _sdk_version() -> str:
    try:
        return version('radicalbit-ai-gateway-sdk')
    except PackageNotFoundError:
        return 'unknown'


USER_AGENT = f'radicalbit-ai-gateway-sdk-python/{_sdk_version()}'


@lru_cache
def _adapter(response_type: Any) -> TypeAdapter[Any]:
    return TypeAdapter(response_type)


def _given(values: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The values the caller gave, as JSON-compatible data (aliases for models)."""
    if values is None:
        return None
    given = {k: v for k, v in values.items() if not isinstance(v, NotGiven)}
    return to_jsonable_python(given, by_alias=True)


@dataclass(frozen=True)
class _Request:
    """One API call, ready to send as many times as the retries allow."""

    method: str
    url: str
    params: dict[str, Any] | None
    json: dict[str, Any] | None
    data: dict[str, Any] | None
    files: dict[str, Any] | None
    response: Any

    @classmethod
    def build(
        cls,
        method: str,
        path: str,
        *,
        path_params: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        files: Mapping[str, Any] | None = None,
        response: Any = None,
    ) -> _Request:
        segments = _given(path_params) or {}
        url = path.format(**{k: quote(str(v), safe='') for k, v in segments.items()})
        given_files = {
            k: v for k, v in (files or {}).items() if not isinstance(v, NotGiven)
        }
        return cls(
            method=method,
            url=url,
            params=_given(query),
            json=_given(json),
            data=_given(data),
            files=given_files or None,
            response=response,
        )

    @property
    def resendable(self) -> bool:
        """Whether sending the request again sends the same content."""
        return all(_in_memory(f) for f in (self.files or {}).values())

    def parse(self, reply: httpx2.Response) -> Any:
        """The 2xx body as the operation's response model, or a typed error."""
        if not reply.is_success:
            raise error_from_response(reply.status_code, reply.content)
        if self.response is None:
            return None
        return _adapter(self.response).validate_json(reply.content)


def _in_memory(file: Any) -> bool:
    content = file[1] if isinstance(file, tuple) else file
    return isinstance(content, bytes | str)


def _wait_after_status(
    request: _Request, reply: httpx2.Response, attempt: int
) -> float | None:
    """Seconds to wait before sending again after an error status, or None."""
    retriable = reply.status_code in _RETRY_ANY_METHOD or (
        reply.status_code in _RETRY_IDEMPOTENT and request.method in _IDEMPOTENT_METHODS
    )
    if not retriable:
        return None
    return _retry_after(reply.headers) or _backoff(attempt)


def _wait_after_error(
    request: _Request, error: httpx2.TransportError, attempt: int
) -> float | None:
    """Seconds to wait before sending again after a network error, or None."""
    if isinstance(error, _NOT_SENT) or request.method in _IDEMPOTENT_METHODS:
        return _backoff(attempt)
    return None


def _backoff(attempt: int) -> float:
    return min(_FIRST_WAIT * 2**attempt, _MAX_WAIT) * random.uniform(0.75, 1.0)


def _retry_after(headers: httpx2.Headers) -> float | None:
    """The wait the answer asks for, if usable: ``retry-after-ms``, or
    ``Retry-After`` in seconds or as a date.
    """
    try:
        seconds = float(headers['retry-after-ms']) / 1000
        return seconds if 0 <= seconds <= _MAX_RETRY_AFTER else None
    except (KeyError, ValueError):
        pass
    value = headers.get('retry-after')
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = email.utils.parsedate_to_datetime(value).timestamp() - time.time()
        except (TypeError, ValueError):
            return None
    return seconds if 0 <= seconds <= _MAX_RETRY_AFTER else None


def _connection_error(error: httpx2.TransportError) -> APIConnectionError:
    if isinstance(error, httpx2.TimeoutException):
        return APITimeoutError()
    return APIConnectionError(f'Could not reach the gateway: {error}')


def _base_url(base_url: str | None) -> str:
    url = base_url or os.environ.get(BASE_URL_ENV)
    if not url:
        raise ValueError(
            f'No gateway URL: pass base_url or set the {BASE_URL_ENV} '
            'environment variable'
        )
    return url.rstrip('/')


class _Options:
    """What every request of a client sends besides its own arguments."""

    _timeout: float | httpx2.Timeout
    _max_retries: int
    _headers: dict[str, str]

    def _set_options(
        self,
        timeout: float | httpx2.Timeout,
        max_retries: int,
        headers: Mapping[str, str] | None,
    ) -> None:
        if max_retries < 0:
            raise ValueError('max_retries must be 0 or more')
        self._timeout = timeout
        self._max_retries = max_retries
        self._headers = dict(headers or {})

    def _copy_with(
        self,
        timeout: float | httpx2.Timeout | NotGiven,
        max_retries: int | NotGiven,
        headers: Mapping[str, str] | NotGiven,
    ) -> Self:
        clone = object.__new__(type(self))
        clone.__dict__.update(self.__dict__)
        clone._set_options(
            self._timeout if isinstance(timeout, NotGiven) else timeout,
            self._max_retries if isinstance(max_retries, NotGiven) else max_retries,
            self._headers
            if isinstance(headers, NotGiven)
            else {**self._headers, **headers},
        )
        return clone


class Gateway(_Options, Resources):
    """A client of the management API of a Radicalbit AI Gateway.

    ``base_url`` defaults to the ``RADICALBIT_GATEWAY_BASE_URL`` environment
    variable. ``timeout`` is in seconds (or an ``httpx2.Timeout``), and
    ``max_retries`` how many times a failed call is sent again when that is
    safe (see the module's docstring). ``auth`` is any ``httpx2.Auth`` (the
    hook for authenticated deployments), ``transport`` any ``httpx2``
    transport (e.g. ``httpx2.MockTransport`` in tests), ``headers`` are sent
    with every request.
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        auth: httpx2.Auth | None = None,
        timeout: float | httpx2.Timeout = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        transport: httpx2.BaseTransport | None = None,
        headers: Mapping[str, str] | None = None,
    ):
        self._set_options(timeout, max_retries, None)
        self._http = httpx2.Client(
            base_url=_base_url(base_url),
            auth=auth,
            timeout=timeout,
            transport=transport,
            headers={'User-Agent': USER_AGENT, **(headers or {})},
        )
        Resources.__init__(self, self)

    def with_options(
        self,
        *,
        timeout: float | httpx2.Timeout | NotGiven = NOT_GIVEN,
        max_retries: int | NotGiven = NOT_GIVEN,
        headers: Mapping[str, str] | NotGiven = NOT_GIVEN,
    ) -> Gateway:
        """A client with these options, for the calls made through it.

        It shares the connections of this one: close this one, not the copy.
        ``gw.with_options(timeout=120).configs.validate(...)``.
        """
        clone = self._copy_with(timeout, max_retries, headers)
        Resources.__init__(clone, clone)
        return clone

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Gateway:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **operation: Any) -> Any:
        """Send one call, retried when safe: the parsed body, or a typed error."""
        request = _Request.build(method, path, **operation)
        retries = self._max_retries if request.resendable else 0
        for attempt in range(retries + 1):
            last = attempt == retries
            try:
                reply = self._http.request(
                    request.method,
                    request.url,
                    params=request.params,
                    json=request.json,
                    data=request.data,
                    files=request.files,
                    headers=self._headers,
                    timeout=self._timeout,
                )
            except httpx2.TransportError as error:
                wait = None if last else _wait_after_error(request, error, attempt)
                if wait is None:
                    raise _connection_error(error) from error
                _sleep(wait)
                continue
            wait = None if last else _wait_after_status(request, reply, attempt)
            if wait is None:
                return request.parse(reply)
            _sleep(wait)
        raise AssertionError('unreachable: the last attempt returns or raises')


class AsyncGateway(_Options, AsyncResources):
    """The async client: ``Gateway``'s options, methods awaited.

    ``async with AsyncGateway(...) as gw: project = await gw.projects.get(uuid)``.
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        auth: httpx2.Auth | None = None,
        timeout: float | httpx2.Timeout = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        transport: httpx2.AsyncBaseTransport | None = None,
        headers: Mapping[str, str] | None = None,
    ):
        self._set_options(timeout, max_retries, None)
        self._http = httpx2.AsyncClient(
            base_url=_base_url(base_url),
            auth=auth,
            timeout=timeout,
            transport=transport,
            headers={'User-Agent': USER_AGENT, **(headers or {})},
        )
        AsyncResources.__init__(self, self)

    def with_options(
        self,
        *,
        timeout: float | httpx2.Timeout | NotGiven = NOT_GIVEN,
        max_retries: int | NotGiven = NOT_GIVEN,
        headers: Mapping[str, str] | NotGiven = NOT_GIVEN,
    ) -> AsyncGateway:
        """A client with these options, sharing this one's connections."""
        clone = self._copy_with(timeout, max_retries, headers)
        AsyncResources.__init__(clone, clone)
        return clone

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> AsyncGateway:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def _request(self, method: str, path: str, **operation: Any) -> Any:
        """Send one call, retried when safe: the parsed body, or a typed error."""
        request = _Request.build(method, path, **operation)
        retries = self._max_retries if request.resendable else 0
        for attempt in range(retries + 1):
            last = attempt == retries
            try:
                reply = await self._http.request(
                    request.method,
                    request.url,
                    params=request.params,
                    json=request.json,
                    data=request.data,
                    files=request.files,
                    headers=self._headers,
                    timeout=self._timeout,
                )
            except httpx2.TransportError as error:
                wait = None if last else _wait_after_error(request, error, attempt)
                if wait is None:
                    raise _connection_error(error) from error
                await _async_sleep(wait)
                continue
            wait = None if last else _wait_after_status(request, reply, attempt)
            if wait is None:
                return request.parse(reply)
            await _async_sleep(wait)
        raise AssertionError('unreachable: the last attempt returns or raises')
