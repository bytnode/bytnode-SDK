from __future__ import annotations

import httpx
import pytest
import respx

from bytnode import (
    APIConnectionError,
    AsyncBytnode,
    AuthenticationError,
    Bytnode,
    InvalidRequestError,
    MissingAPIKeyError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServerError,
)

from .conftest import BASE

OK = {"status": "ok", "server_time": "2026-10-12T09:00:00.000Z", "data_type": "funding_rate", "data": None}


def err(code: str, message: str, param: str | None = None) -> dict[str, object]:
    e: dict[str, object] = {"code": code, "message": message}
    if param:
        e["param"] = param
    return {"status": "error", "server_time": "2026-10-12T09:00:00.000Z", "error": e}


def test_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BYTNODE_API_KEY", raising=False)
    with pytest.raises(MissingAPIKeyError, match="BYTNODE_API_KEY"):
        Bytnode()


def test_key_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYTNODE_API_KEY", "cb_live_from_env")
    assert Bytnode().api_key == "cb_live_from_env"


@respx.mock(base_url=BASE)
def test_retries_503_then_succeeds(respx_mock: respx.MockRouter, client: Bytnode) -> None:
    route = respx_mock.get("/v1/funding/rate").mock(
        side_effect=[httpx.Response(503, json=err("service_unavailable", "busy")), httpx.Response(200, json=OK)]
    )
    resp = client.funding.rate("BTCUSDT")
    assert resp.data is None and route.call_count == 2


@respx.mock(base_url=BASE)
def test_gives_up_after_max_retries(respx_mock: respx.MockRouter, client: Bytnode) -> None:
    route = respx_mock.get("/v1/funding/rate").mock(return_value=httpx.Response(502, text="bad gateway"))
    with pytest.raises(ServerError) as exc:
        client.funding.rate("BTCUSDT")
    assert route.call_count == 4  # 1 + 3 retries
    assert exc.value.status == 502


@respx.mock(base_url=BASE)
def test_500_is_retried_once(respx_mock: respx.MockRouter, client: Bytnode) -> None:
    route = respx_mock.get("/v1/funding/rate").mock(
        return_value=httpx.Response(500, json=err("internal_error", "boom"))
    )
    with pytest.raises(ServerError):
        client.funding.rate("BTCUSDT")
    assert route.call_count == 2


@respx.mock(base_url=BASE)
def test_rate_limit_is_retried_with_retry_after(respx_mock: respx.MockRouter, client: Bytnode) -> None:
    route = respx_mock.get("/v1/funding/rate").mock(
        side_effect=[
            httpx.Response(
                429, json=err("rate_limited", "slow down"), headers={"Retry-After": "2", "X-Deny-Reason": "rate"}
            ),
            httpx.Response(200, json=OK),
        ]
    )
    client.funding.rate("BTCUSDT")
    assert route.call_count == 2


@respx.mock(base_url=BASE)
def test_spent_quota_is_not_retried(respx_mock: respx.MockRouter, client: Bytnode) -> None:
    route = respx_mock.get("/v1/funding/rate").mock(
        return_value=httpx.Response(
            429,
            json=err("quota_exceeded", "monthly quota spent"),
            headers={"Retry-After": "86400", "X-Deny-Reason": "quota"},
        )
    )
    with pytest.raises(RateLimitError) as exc:
        client.funding.rate("BTCUSDT")
    assert route.call_count == 1
    assert exc.value.is_quota and exc.value.retry_after == 86400


@respx.mock(base_url=BASE)
def test_long_retry_after_fails_fast(respx_mock: respx.MockRouter, client: Bytnode) -> None:
    respx_mock.get("/v1/funding/rate").mock(
        return_value=httpx.Response(429, json=err("rate_limited", "x"), headers={"Retry-After": "600"})
    )
    with pytest.raises(RateLimitError) as exc:
        client.funding.rate("BTCUSDT")
    assert not exc.value.is_quota


@pytest.mark.parametrize(
    ("status", "body", "headers", "cls"),
    [
        (
            401,
            err("invalid_api_key", "API key missing, invalid or revoked."),
            {"X-Deny-Reason": "key"},
            AuthenticationError,
        ),
        (403, err("plan_family", "not in your plan"), {"X-Deny-Reason": "family"}, PermissionDeniedError),
        (403, err("history_depth", "beyond your plan's history"), {"X-Deny-Reason": "depth"}, PermissionDeniedError),
        (404, err("not_found", "retired, use /v1/klines"), {}, NotFoundError),
        (422, err("invalid_symbol", "Unknown symbol 'FAKE'.", "symbol"), {}, InvalidRequestError),
    ],
)
@respx.mock(base_url=BASE)
def test_errors_are_typed(
    respx_mock: respx.MockRouter,
    client: Bytnode,
    status: int,
    body: dict[str, object],
    headers: dict[str, str],
    cls: type,
) -> None:
    route = respx_mock.get("/v1/funding/rate").mock(return_value=httpx.Response(status, json=body, headers=headers))
    with pytest.raises(cls) as exc:
        client.funding.rate("BTCUSDT")
    assert route.call_count == 1  # client errors are never retried
    e = exc.value
    assert e.status == status and e.code == body["error"]["code"]  # type: ignore[index]
    assert e.reason == headers.get("X-Deny-Reason")
    assert e.message in str(e)


@respx.mock(base_url=BASE)
def test_param_is_reported(respx_mock: respx.MockRouter, client: Bytnode) -> None:
    respx_mock.get("/v1/klines").mock(
        return_value=httpx.Response(422, json=err("invalid_timeframe", "bad", "timeframe"))
    )
    with pytest.raises(InvalidRequestError) as exc:
        client.klines("BTCUSDT", "1h")
    assert exc.value.param == "timeframe" and "(param: timeframe)" in str(exc.value)


@respx.mock(base_url=BASE)
def test_network_errors_are_retried_then_raised(respx_mock: respx.MockRouter, client: Bytnode) -> None:
    route = respx_mock.get("/v1/funding/rate").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(APIConnectionError):
        client.funding.rate("BTCUSDT")
    assert route.call_count == 4


@respx.mock(base_url=BASE)
def test_non_json_body(respx_mock: respx.MockRouter, client: Bytnode) -> None:
    respx_mock.get("/v1/funding/rate").mock(return_value=httpx.Response(404, text="<html>nope</html>"))
    with pytest.raises(NotFoundError) as exc:
        client.funding.rate("BTCUSDT")
    assert "nope" in exc.value.message


@respx.mock(base_url=BASE)
def test_request_options_override(respx_mock: respx.MockRouter, client: Bytnode) -> None:
    route = respx_mock.get("/v1/funding/rate").mock(
        return_value=httpx.Response(503, json=err("service_unavailable", "x"))
    )
    with pytest.raises(ServerError):
        client.funding.rate("BTCUSDT", request_options={"max_retries": 0, "headers": {"X-Trace": "1"}})
    assert route.call_count == 1
    assert route.calls.last.request.headers["X-Trace"] == "1"


@respx.mock(base_url=BASE)
def test_rate_limit_headers(respx_mock: respx.MockRouter, client: Bytnode) -> None:
    respx_mock.get("/v1/funding/rate").mock(
        return_value=httpx.Response(
            200,
            json=OK,
            headers={
                "RateLimit-Policy": '"rate";q=600;w=60, "quota";q=100000;w=2592000',
                "RateLimit": '"rate";r=599;t=1, "quota";r=87342;t=1234567',
            },
        )
    )
    resp = client.funding.rate("BTCUSDT")
    rl = resp.rate_limit
    assert rl is not None
    assert (rl.limit, rl.remaining, rl.window_s) == (600, 599, 60)
    assert (rl.quota_limit, rl.quota_remaining, rl.quota_reset_s) == (100000, 87342, 1234567)
    assert client.last_rate_limit == rl


@respx.mock(base_url=BASE)
async def test_async_client(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/v1/funding/rate").mock(
        side_effect=[httpx.Response(503, json=err("service_unavailable", "x")), httpx.Response(200, json=OK)]
    )
    async with AsyncBytnode(api_key="cb_live_k", base_url=BASE) as client:
        resp = await client.funding.rate("BTCUSDT")
    assert resp.data_type == "funding_rate"


def test_contract_drift_major_and_newer_minor() -> None:
    from bytnode._response import contract_drift

    assert contract_drift("3.1.0", "3.1.0") is None
    assert contract_drift("3.0.0", "3.1.0") is None  # an older minor: nothing missing for the caller
    assert "MINOR" in (contract_drift("3.2.0", "3.1.0") or "")
    assert "MAJOR" in (contract_drift("4.0.0", "3.1.0") or "")
