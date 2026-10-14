from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

import voices_az
from voices_az import _base
from voices_az.exceptions import (
    APIStatusError,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    ContentPolicyError,
    IdempotencyInProgressError,
    InsufficientBalanceError,
    NotFoundError,
    PayloadTooLargeError,
    PermissionDeniedError,
    ProjectExpiredError,
    RateLimitError,
    ServerError,
    ValidationError,
    VoicesError,
)

from .conftest import API_KEY, BASE, fail, ok

# ----------------------------------------------------------------------------- envelope


def test_success_envelope_returns_data(client, api):
    api.get("/customer/balance").mock(return_value=ok({"balance": {"amount": "12.40",
                                                                   "currency": "AZN"}}))
    balance = client.account.balance()
    assert balance.amount == Decimal("12.40")
    assert balance.currency == "AZN"
    assert balance.raw == {"balance": {"amount": "12.40", "currency": "AZN"}}


def test_success_false_on_200_is_an_error(client, api):
    api.get("/services").mock(return_value=httpx.Response(200, json={
        "success": False, "error": {"message": "nope", "code": 404, "type": "not_found"}}))
    with pytest.raises(NotFoundError) as exc:
        client.services.list()
    assert exc.value.status_code == 404


def test_body_without_envelope_is_returned_as_is(client, api):
    api.get("/services").mock(return_value=httpx.Response(200, json={"services": []}))
    assert client.services.list() == []


def test_low_level_request(client, api):
    route = api.get("/service/dubbing").mock(return_value=ok({"service": {"slug": "dubbing"}}))
    assert client.request("get", "/service/dubbing", params={"x": 1}) == {
        "service": {"slug": "dubbing"}}
    assert route.calls.last.request.url.params["x"] == "1"


# ----------------------------------------------------------------------------- headers


def test_headers(client, api):
    route = api.get("/services").mock(return_value=ok({"services": []}))
    client.services.list()
    headers = route.calls.last.request.headers
    assert headers["X-API-KEY"] == API_KEY
    assert headers["Accept"] == "application/json"
    assert headers["User-Agent"].startswith("voices-az-python/")
    assert "Accept-Language" not in headers
    assert "Idempotency-Key" not in headers
    assert "Authorization" not in headers


def test_accept_language(api):
    route = api.get("/services").mock(return_value=ok({"services": []}))
    with voices_az.Client(api_key=API_KEY, base_url=BASE, language="ru-RU") as c:
        c.services.list()
    assert route.calls.last.request.headers["Accept-Language"] == "ru"


def test_unsupported_language_option():
    with pytest.raises(ValueError):
        voices_az.Client(api_key=API_KEY, language="de")


def test_api_key_from_environment(monkeypatch):
    monkeypatch.setenv("VOICES_API_KEY", " vz_live_env ")
    monkeypatch.setenv("VOICES_BASE_URL", "https://example.test/api/")
    c = voices_az.Client()
    assert c.api_key == "vz_live_env"
    assert c.base_url == "https://example.test/api"
    assert "vz_live_env" not in repr(c)
    c.close()


def test_missing_api_key(monkeypatch):
    monkeypatch.delenv("VOICES_API_KEY", raising=False)
    with pytest.raises(VoicesError, match="VOICES_API_KEY"):
        voices_az.Client()


def test_negative_retries_rejected():
    with pytest.raises(ValueError):
        voices_az.Client(api_key="k", max_retries=-1)


def test_poll_interval_floor():
    c = voices_az.Client(api_key="k", poll_interval=0.1)
    assert c.poll_interval == 2.0
    c.close()


def test_context_manager_closes_own_http_client():
    c = voices_az.Client(api_key="k")
    with c:
        pass
    assert c._http.is_closed


def test_external_http_client_is_not_closed():
    http = httpx.Client()
    voices_az.Client(api_key="k", http_client=http).close()
    assert not http.is_closed
    http.close()


# ----------------------------------------------------------------------------- mapping


@pytest.mark.parametrize("status,type_,cls", [
    (400, "bad_request", BadRequestError),
    (401, "unauthenticated", AuthenticationError),
    (403, "api_key_scope", PermissionDeniedError),
    (404, "not_found", NotFoundError),
    (405, "method_not_allowed", APIStatusError),
    (409, "conflict", ConflictError),
    (409, "idempotency_in_progress", IdempotencyInProgressError),
    (413, "payload_too_large", PayloadTooLargeError),
    (422, "validation_failed", ValidationError),
    (422, "idempotency_key_reused", ValidationError),
    (422, "content_policy", ContentPolicyError),
    (500, "server_error", ServerError),
])
def test_error_classes(client, api, status, type_, cls):
    api.get("/services").mock(return_value=fail(status, type_, "Localised message"))
    with pytest.raises(cls) as exc:
        client.services.list()
    err = exc.value
    assert type(err) is cls
    assert err.status_code == status
    assert err.type == type_
    assert err.message == "Localised message"
    assert f"HTTP {status}" in str(err)
    assert err.body["success"] is False
    assert err.response.status_code == status
    assert isinstance(err, VoicesError)


def test_content_policy_is_not_a_validation_error(client, api):
    api.post("/services/text-to-speech/synthesize").mock(
        return_value=fail(422, "content_policy", "This text cannot be processed."))
    with pytest.raises(ContentPolicyError) as exc:
        client.tts.synthesize("…", wait=False)
    assert not isinstance(exc.value, ValidationError)


def test_project_expired(client, api):
    api.post("/services/text-to-speech/export/7420").mock(return_value=fail(
        410, "gone", "Files deleted",
        data={"project_id": 7420, "expired_at": "2026-03-18T04:00:11+04:00"}))
    with pytest.raises(ProjectExpiredError) as exc:
        client.tts.export(7420)
    assert exc.value.project_id == 7420
    assert exc.value.expired_at == "2026-03-18T04:00:11+04:00"


def test_validation_error_with_field_errors(client, api):
    # What the API really sends for a form-validation failure.
    api.post("/services/text-to-speech/synthesize").mock(return_value=httpx.Response(
        422, json={"status": "error", "message": "The text field is required.",
                   "errors": {"text": ["The text field is required."], "speed": "bad"}}))
    with pytest.raises(ValidationError) as exc:
        client.tts.synthesize("x", wait=False)
    err = exc.value
    assert type(err) is ValidationError
    assert err.type == "validation_failed"
    assert err.message == "The text field is required."
    assert err.errors == {"text": ["The text field is required."], "speed": ["bad"]}


def test_insufficient_balance_real_shape(client, api):
    api.post("/services/text-to-speech/export/55").mock(return_value=httpx.Response(422, json={
        "status": "error",
        "message": "Your balance is not sufficient for this operation.",
        "errors": {"balance": ["Your balance is not sufficient for this operation."]},
        "data": {"reason": "insufficient_balance", "price": "0.50", "balance": "0.20",
                 "missing": "0.50", "currency": "AZN", "project_id": 55},
    }))
    with pytest.raises(InsufficientBalanceError) as exc:
        client.tts.export(55)
    err = exc.value
    assert isinstance(err, ValidationError)
    assert err.reason == "insufficient_balance"
    assert err.price == Decimal("0.50")
    assert err.balance == Decimal("0.20")
    assert err.missing == Decimal("0.50")
    assert err.currency == "AZN"
    assert err.project_id == 55
    assert "balance" in err.errors


def test_insufficient_balance_documented_shape(client, api):
    api.post("/services/dubbing/generate/9").mock(return_value=fail(
        422, "validation_failed", "Your balance is not sufficient for this operation.",
        data={"reason": "insufficient_balance", "price": "2.10", "balance": "1",
              "missing": "1.10", "currency": "AZN", "project_id": None}))
    with pytest.raises(InsufficientBalanceError) as exc:
        client.dubbing.generate(9)
    assert exc.value.missing == Decimal("1.10")
    assert exc.value.project_id is None


def test_insufficient_balance_without_figures(client, api):
    api.post("/services/text-to-speech/export/1").mock(return_value=httpx.Response(422, json={
        "status": "error", "message": "Low balance", "errors": {"balance": ["Low balance"]}}))
    with pytest.raises(InsufficientBalanceError) as exc:
        client.tts.export(1)
    assert exc.value.price is None and exc.value.missing is None


def test_rate_limit_error_fields(api, fake_time):
    api.get("/services").mock(return_value=fail(
        429, "rate_limited", "Too many", headers={"Retry-After": "120",
                                                   "X-RateLimit-Limit": "60",
                                                   "X-RateLimit-Remaining": "0"}))
    with voices_az.Client(api_key=API_KEY, base_url=BASE) as c:
        c._sleep = fake_time.sleep
        with pytest.raises(RateLimitError) as exc:
            c.services.list()
    err = exc.value
    assert err.retry_after == 120
    assert err.limit == 60
    assert err.remaining == 0
    # Retry-After over a minute is not waited out silently.
    assert fake_time.sleeps == []


def test_non_json_error_body(client, api):
    api.get("/services").mock(return_value=httpx.Response(
        418, text="<html>teapot</html>"))
    with pytest.raises(APIStatusError) as exc:
        client.services.list()
    assert exc.value.status_code == 418
    assert exc.value.body is None
    assert exc.value.message == "HTTP 418"


def test_redirect_is_reported(client, api):
    api.get("/services").mock(return_value=httpx.Response(
        301, headers={"Location": "https://voices.az/en/api/services"}))
    with pytest.raises(APIStatusError, match="check base_url") as exc:
        client.services.list()
    assert exc.value.status_code == 301


def test_error_with_string_error_field():
    response = httpx.Response(401, json={"error": "Unauthenticated."})
    err = _base.make_error(response)
    assert isinstance(err, AuthenticationError)
    assert err.message == "Unauthenticated."


def test_error_with_text_body():
    err = _base.make_error(httpx.Response(400, text="bad things"), "bad things")
    assert err.message == "bad things"


def test_parse_retry_after():
    assert _base.parse_retry_after(None) is None
    assert _base.parse_retry_after("") is None
    assert _base.parse_retry_after("3") == 3.0
    assert _base.parse_retry_after("-3") == 0.0
    assert _base.parse_retry_after("garbage") is None
    when = _base.parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT", now=1445412470.0)
    assert when == pytest.approx(10.0)


def test_status_error_headers_without_response():
    err = APIStatusError("x", status_code=500)
    assert dict(err.headers) == {}
    assert str(err) == "x (HTTP 500)"


def test_api_timeout_and_connection_messages():
    assert "timed out" in str(voices_az.APITimeoutError())
    assert isinstance(voices_az.APITimeoutError(), voices_az.APIConnectionError)


def test_timeout_error_is_builtin_timeout():
    err = voices_az.TimeoutError("late", request_id="r", project_id=1)
    assert isinstance(err, TimeoutError.__mro__[0])
    import builtins
    assert isinstance(err, builtins.TimeoutError)
    assert err.request_id == "r" and err.project_id == 1


def test_helpers_on_bad_numbers():
    from voices_az.exceptions import _decimal_or_none, _int_or_none
    assert _decimal_or_none("x") is None
    assert _decimal_or_none("") is None
    assert _int_or_none("x") is None
    assert _int_or_none(None) is None
