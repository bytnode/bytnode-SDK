"""HTTP: building requests, retrying what is worth retrying, turning errors into exceptions."""

from __future__ import annotations

import asyncio
import json
import platform
import random
import time
from collections.abc import Mapping
from typing import Any, NoReturn
from urllib.parse import quote

import httpx

from ._errors import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    _retry_after,
    error_from_response,
)
from ._routes import RouteSpec
from ._time import TIME_PARAMS, to_ms
from ._types import RequestOptions
from ._version import __version__

DEFAULT_BASE_URL = "https://api.bytnode.com"
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 3
# Beyond this wait the 429 is not a burst but a spent quota: fail fast, never sleep an hour.
MAX_RETRY_AFTER_S = 60.0
RETRY_STATUSES = frozenset({429, 502, 503, 504})

USER_AGENT = f"bytnode-python/{__version__} httpx/{httpx.__version__} python/{platform.python_version()}"


def encode_value(name: str, value: Any) -> Any:
    """One query value, as the API expects it."""
    if value is None:
        return None
    if name in TIME_PARAMS:
        return to_ms(value, name.removesuffix("_ms"))
    if name == "fields" and not isinstance(value, str):
        return ",".join(str(v) for v in value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def build_request(route: RouteSpec, params: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """The URL path (path parameters filled in) and the query of a call."""
    path = route.path
    query: dict[str, Any] = {}
    for name, value in params.items():
        if name in route.path_params:
            if value is None or value == "":
                raise ValueError(f"{name} is required")
            path = path.replace("{" + name + "}", quote(str(value), safe=""))
            continue
        encoded = encode_value(name, value)
        if encoded is not None:
            query[name] = encoded
    return path, query


def _backoff(attempt: int) -> float:
    """0.5 s, 1 s, 2 s... capped at 8 s, with jitter so clients do not retry in lockstep."""
    return min(8.0, 0.5 * 2.0**attempt) * (0.5 + random.random() / 2)  # noqa: S311 (not crypto)


def retry_delay(response: httpx.Response | None, attempt: int, max_retries: int) -> float | None:
    """Seconds to wait before retrying, or `None` when the error must be raised now."""
    if attempt >= max_retries:
        return None
    if response is None:  # network error: the request may not have reached the API
        return _backoff(attempt)
    status = response.status_code
    if status == 500:
        return _backoff(attempt) if attempt == 0 else None  # once: an internal error is rarely transient
    if status not in RETRY_STATUSES:
        return None
    if status == 429:
        reason = response.headers.get("x-deny-reason")
        if reason == "quota" or b"quota_exceeded" in response.content:
            return None
        wait = _retry_after(response.headers)
        if wait is not None:
            return None if wait > MAX_RETRY_AFTER_S else wait + random.random() * 0.25  # noqa: S311
    return _backoff(attempt)


class _Base:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout: float,
        max_retries: int,
        default_headers: Mapping[str, str] | None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.headers = {
            "X-API-KEY": api_key,
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "User-Agent": USER_AGENT,
            **(default_headers or {}),
        }

    def _options(self, options: RequestOptions | None) -> tuple[float, int, dict[str, str]]:
        options = options or {}
        headers = {**self.headers, **dict(options.get("headers") or {})}
        return options.get("timeout", self.timeout), options.get("max_retries", self.max_retries), headers

    @staticmethod
    def _raise_for(response: httpx.Response) -> NoReturn:
        raise error_from_response(response.status_code, response.headers, response.content)

    @staticmethod
    def _decode(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError):
            raise APIError(
                response.status_code,
                f"the API answered with a non-JSON body ({response.headers.get('content-type')})",
                headers=response.headers,
                body=response.text[:500],
            ) from None
        if not isinstance(body, dict):
            raise APIError(response.status_code, "unexpected response body", headers=response.headers, body=body)
        return body


class SyncTransport(_Base):
    def __init__(self, *args: Any, http_client: httpx.Client | None = None) -> None:
        super().__init__(*args)
        self._owns = http_client is None
        self.client = http_client or httpx.Client(timeout=self.timeout, http2=False, follow_redirects=False)

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        body: Any = None,
        options: RequestOptions | None = None,
    ) -> tuple[httpx.Response, dict[str, Any]]:
        timeout, max_retries, headers = self._options(options)
        url = self.base_url + path
        attempt = 0
        while True:
            try:
                response = self.client.request(method, url, params=query, json=body, headers=headers, timeout=timeout)
            except httpx.TimeoutException as exc:
                delay = retry_delay(None, attempt, max_retries)
                if delay is None:
                    raise APITimeoutError(f"no answer from {url} within {timeout} s") from exc
            except httpx.TransportError as exc:
                delay = retry_delay(None, attempt, max_retries)
                if delay is None:
                    raise APIConnectionError(f"could not reach {url}: {exc}") from exc
            else:
                if response.status_code < 400:
                    return response, self._decode(response)
                delay = retry_delay(response, attempt, max_retries)
                if delay is None:
                    self._raise_for(response)
            time.sleep(delay)
            attempt += 1

    def close(self) -> None:
        if self._owns:
            self.client.close()


class AsyncTransport(_Base):
    def __init__(self, *args: Any, http_client: httpx.AsyncClient | None = None) -> None:
        super().__init__(*args)
        self._owns = http_client is None
        self.client = http_client or httpx.AsyncClient(timeout=self.timeout, follow_redirects=False)

    async def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        body: Any = None,
        options: RequestOptions | None = None,
    ) -> tuple[httpx.Response, dict[str, Any]]:
        timeout, max_retries, headers = self._options(options)
        url = self.base_url + path
        attempt = 0
        while True:
            try:
                response = await self.client.request(
                    method, url, params=query, json=body, headers=headers, timeout=timeout
                )
            except httpx.TimeoutException as exc:
                delay = retry_delay(None, attempt, max_retries)
                if delay is None:
                    raise APITimeoutError(f"no answer from {url} within {timeout} s") from exc
            except httpx.TransportError as exc:
                delay = retry_delay(None, attempt, max_retries)
                if delay is None:
                    raise APIConnectionError(f"could not reach {url}: {exc}") from exc
            else:
                if response.status_code < 400:
                    return response, self._decode(response)
                delay = retry_delay(response, attempt, max_retries)
                if delay is None:
                    self._raise_for(response)
            await asyncio.sleep(delay)
            attempt += 1

    async def aclose(self) -> None:
        if self._owns:
            await self.client.aclose()


__all__ = ["AsyncTransport", "SyncTransport", "build_request"]
