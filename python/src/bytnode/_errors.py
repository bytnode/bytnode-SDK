"""Every error the SDK raises.

    BytnodeError
    ├── MissingAPIKeyError          no key given and BYTNODE_API_KEY not set
    ├── APIConnectionError          the request never got an answer
    │   └── APITimeoutError
    ├── APIError                    the API answered with an error (status, code, message...)
    │   ├── InvalidRequestError     400 / 422: a parameter is wrong (see `.param`)
    │   ├── AuthenticationError     401: key missing, invalid or revoked
    │   ├── PermissionDeniedError   403: outside your plan (see `.reason`)
    │   ├── NotFoundError           404: unknown or retired route
    │   ├── RateLimitError          429: rate limit or monthly quota (see `.retry_after`)
    │   └── ServerError             5xx
    └── StreamError                 a WebSocket error frame or refusal
        └── ConnectionLimitError    the plan's ceiling of simultaneous connections

Branch on `error.code` (stable, see `bytnode.types.ErrorCode`), never on the message.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


class BytnodeError(Exception):
    """Base class of every error raised by the SDK."""


class MissingAPIKeyError(BytnodeError):
    def __init__(self) -> None:
        super().__init__(
            "No API key: pass api_key=... or set the BYTNODE_API_KEY environment variable. "
            "Create a key at https://bytnode.com/dashboard/keys"
        )


class APIConnectionError(BytnodeError):
    """The request did not get an answer (DNS, TLS, connection reset...)."""


class APITimeoutError(APIConnectionError):
    """No answer within the timeout."""


class APIError(BytnodeError):
    """The API answered with an error status.

    Attributes:
        status: HTTP status.
        code: stable `error.code` (`invalid_symbol`, `history_depth`, `rate_limited`...).
        message: English, human-readable explanation from the API.
        param: the parameter at fault, when there is one.
        details: extra structured details, when the API gives some.
        reason: `X-Deny-Reason` header: the `code` of the refusal (`plan_family`, `history_depth`,
            `plan_websocket`, `rate_limited`, `quota_exceeded`...).
        request_id: request identifier, when the API sends one (quote it to support).
        headers: response headers.
        body: the decoded error body (or the raw text if it was not JSON).
    """

    status: int
    code: str | None
    message: str
    param: str | None
    details: Any
    reason: str | None
    request_id: str | None
    headers: Mapping[str, str]
    body: Any

    def __init__(
        self,
        status: int,
        message: str,
        *,
        code: str | None = None,
        param: str | None = None,
        details: Any = None,
        reason: str | None = None,
        request_id: str | None = None,
        headers: Mapping[str, str] | None = None,
        body: Any = None,
    ) -> None:
        self.status = status
        self.code = code
        self.message = message
        self.param = param
        self.details = details
        self.reason = reason
        self.request_id = request_id
        self.headers = headers or {}
        self.body = body
        super().__init__(str(self))

    def __str__(self) -> str:
        head = f"{self.status}"
        if self.code:
            head += f" {self.code}"
        text = f"{head}: {self.message}"
        if self.param:
            text += f" (param: {self.param})"
        if self.request_id:
            text += f" [request_id: {self.request_id}]"
        return text

    def __repr__(self) -> str:
        return f"{type(self).__name__}(status={self.status}, code={self.code!r}, message={self.message!r})"


class InvalidRequestError(APIError):
    """400 or 422: the request is wrong. `.param` names the culprit, the message says what is accepted."""


class AuthenticationError(APIError):
    """401: the key is missing, invalid or revoked."""


class PermissionDeniedError(APIError):
    """403: valid key, but outside your plan.

    `.reason` (or `.code`) says which limit: `family` / `plan_family` (data family not in
    your plan), `depth` / `history_depth` (history window of your plan), `websocket`.
    """


class NotFoundError(APIError):
    """404: unknown route, or a route that was retired (the message names its replacement)."""


class RateLimitError(APIError):
    """429: too many requests, or the monthly quota is spent.

    `.retry_after` is the number of seconds the API asks you to wait (`None` if not given);
    `.is_quota` tells the monthly quota (wait for the next month or upgrade) from the rate
    limit (wait a few seconds; the SDK already retried).
    """

    @property
    def retry_after(self) -> float | None:
        return _retry_after(self.headers)

    @property
    def is_quota(self) -> bool:
        return self.code == "quota_exceeded" or self.reason == "quota"


class ServerError(APIError):
    """5xx: an error on BytNode's side. The SDK already retried 502, 503 and 504."""


class StreamError(BytnodeError):
    """An error on the WebSocket stream: an `op: error` frame, or a closing code."""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        close_code: int | None = None,
        param: str | None = None,
        details: Any = None,
    ) -> None:
        self.code = code
        self.message = message
        self.close_code = close_code
        # The field of your message at fault and the structured complement
        # (`suggestion`, `accepted`), like a REST error (contract 3.0.0).
        self.param = param
        self.details = details
        super().__init__(f"{code}: {message}" if code else message)


class ConnectionLimitError(StreamError):
    """The plan's ceiling on simultaneous WebSocket connections is reached (close 4003)."""


_BY_STATUS: dict[int, type[APIError]] = {
    400: InvalidRequestError,
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    422: InvalidRequestError,
    429: RateLimitError,
}


def _retry_after(headers: Mapping[str, str]) -> float | None:
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        from datetime import datetime, timezone
        from email.utils import parsedate_to_datetime  # an HTTP date

        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


def error_from_response(status: int, headers: Mapping[str, str], content: bytes | str) -> APIError:
    """Build the right `APIError` subclass from an error response."""
    text = content.decode("utf-8", "replace") if isinstance(content, bytes) else content
    body: Any = text
    code = param = None
    details: Any = None
    message = ""
    try:
        body = json.loads(text) if text else None
    except ValueError:
        body = text
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            code = err.get("code")
            message = err.get("message") or ""
            param = err.get("param")
            details = err.get("details")
        elif isinstance(body.get("detail"), str):
            message = body["detail"]
    if not message:
        message = (text or "").strip()[:300] or f"HTTP {status}"
    cls = _BY_STATUS.get(status) or (ServerError if status >= 500 else APIError)
    return cls(
        status,
        message,
        code=code,
        param=param,
        details=details,
        reason=headers.get("x-deny-reason"),
        request_id=headers.get("x-request-id"),
        headers=headers,
        body=body,
    )
