"""Retry rules: what is repeated, what never is."""

from __future__ import annotations

import io

import httpx
import pytest

import voices_az
from voices_az import _base
from voices_az._base import Call

from .conftest import fail, ok

EXPORT = "/services/text-to-speech/export/7"
SYNTH = "/services/text-to-speech/synthesize"


def test_get_is_retried_on_503_then_succeeds(client, api, fake_time):
    route = api.get("/services").mock(side_effect=[
        httpx.Response(503, text="Service Unavailable"),
        httpx.Response(502, text="Bad Gateway"),
        ok({"services": []}),
    ])
    assert client.services.list() == []
    assert route.call_count == 3
    assert len(fake_time.sleeps) == 2
    assert 0.3 < fake_time.sleeps[0] < 0.7 and 0.7 < fake_time.sleeps[1] < 1.3


def test_get_gives_up_after_max_retries(client, api):
    route = api.get("/services").mock(return_value=httpx.Response(504))
    with pytest.raises(voices_az.ServerError):
        client.services.list()
    assert route.call_count == 3  # 1 + max_retries(2)


def test_500_is_never_retried(client, api):
    route = api.get("/services").mock(return_value=fail(500, "server_error"))
    with pytest.raises(voices_az.ServerError):
        client.services.list()
    assert route.call_count == 1


def test_get_is_retried_on_network_errors(client, api):
    route = api.get("/services").mock(side_effect=[
        httpx.ReadTimeout("slow"), httpx.RemoteProtocolError("reset"), ok({"services": []})])
    assert client.services.list() == []
    assert route.call_count == 3


def test_network_error_after_retries_is_wrapped(client, api):
    api.get("/services").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(voices_az.APIConnectionError) as exc:
        client.services.list()
    assert not isinstance(exc.value, voices_az.APITimeoutError)
    assert isinstance(exc.value.__cause__, httpx.ConnectError)


def test_timeout_after_retries_is_wrapped(client, api):
    api.get("/services").mock(side_effect=httpx.ConnectTimeout("slow"))
    with pytest.raises(voices_az.APITimeoutError):
        client.services.list()


def test_export_is_never_retried_on_gateway_errors(client, api):
    route = api.post(EXPORT).mock(return_value=httpx.Response(502))
    with pytest.raises(voices_az.ServerError):
        client.tts.export(7)
    assert route.call_count == 1


def test_export_is_never_retried_after_a_read_timeout(client, api):
    route = api.post(EXPORT).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(voices_az.APITimeoutError):
        client.tts.export(7)
    assert route.call_count == 1


def test_export_is_retried_when_the_connection_never_opened(client, api):
    # Nothing reached the API, so nothing can have been charged.
    route = api.post(EXPORT).mock(side_effect=[
        httpx.ConnectError("refused"), ok({"title": "t", "file": "https://f/x.mp3"})])
    assert client.tts.export(7).file == "https://f/x.mp3"
    assert route.call_count == 2


def test_rate_limited_export_is_retried_after_retry_after(client, api, fake_time):
    # 429 is answered by the rate limiter before the request runs.
    route = api.post(EXPORT).mock(side_effect=[
        fail(429, "rate_limited", headers={"Retry-After": "7"}),
        ok({"title": "t", "file": "https://f/x.mp3"}),
    ])
    client.tts.export(7)
    assert route.call_count == 2
    assert fake_time.sleeps == [7.0]


def test_charging_call_with_idempotency_key_is_retried_with_the_same_key(client, api):
    route = api.post(SYNTH).mock(side_effect=[
        httpx.ReadTimeout("slow"),
        httpx.Response(502),
        ok({"request_id": "r1", "project": 5}),
    ])
    result = client.tts.synthesize("Salam", wait=False)
    assert result.request_id == "r1" and result.project_id == 5
    keys = {c.request.headers["Idempotency-Key"] for c in route.calls}
    assert route.call_count == 3
    assert len(keys) == 1
    assert len(keys.pop()) == 36  # a uuid


def test_caller_idempotency_key_is_used(client, api):
    route = api.post(SYNTH).mock(return_value=ok({"request_id": "r", "project": 1}))
    client.tts.synthesize("Salam", wait=False, idempotency_key="order-42")
    assert route.calls.last.request.headers["Idempotency-Key"] == "order-42"


def test_idempotency_in_progress_is_retried(client, api, fake_time):
    route = api.post(SYNTH).mock(side_effect=[
        fail(409, "idempotency_in_progress"), ok({"request_id": "r", "project": 1})])
    client.tts.synthesize("Salam", wait=False)
    assert route.call_count == 2


def test_plain_conflict_is_not_retried(client, api):
    route = api.post(SYNTH).mock(return_value=fail(409, "conflict"))
    with pytest.raises(voices_az.ConflictError):
        client.tts.synthesize("Salam", wait=False)
    assert route.call_count == 1


def test_max_retries_zero_disables_retries(api, fake_time):
    route = api.get("/services").mock(return_value=httpx.Response(503))
    with voices_az.Client(api_key="k", base_url="https://api.voices.test/api",
                          max_retries=0) as c, pytest.raises(voices_az.ServerError):
        c.services.list()
    assert route.call_count == 1


def test_upload_is_replayed_in_full(client, api, tmp_path):
    source = tmp_path / "talk.wav"
    source.write_bytes(b"RIFF" + b"x" * 5000)
    route = api.post("/services/speech-to-text/recognize").mock(side_effect=[
        fail(429, "rate_limited", headers={"Retry-After": "1"}),
        httpx.Response(503),
        ok({"project_id": 9, "request_id": "r"}),
    ])
    client.stt.recognize(source, language=6, wait=False)
    assert route.call_count == 3
    bodies = [c.request.read() for c in route.calls]
    assert all(b"x" * 5000 in body for body in bodies)


def test_rewindable_stream_is_replayed(client, api):
    stream = io.BytesIO(b"HEADER" + b"y" * 100)
    route = api.post("/services/speech-to-text/recognize").mock(side_effect=[
        httpx.Response(503), ok({"project_id": 9})])
    client.stt.recognize(stream, filename="a.wav", language=6, wait=False)
    bodies = [c.request.read() for c in route.calls]
    assert route.call_count == 2
    assert all(b"HEADER" + b"y" * 100 in b for b in bodies)


class OneShot(io.RawIOBase):
    """A readable stream that cannot seek (like a pipe)."""

    def __init__(self, data: bytes) -> None:
        self._data = io.BytesIO(data)

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False

    def readinto(self, b):  # type: ignore[no-untyped-def]
        chunk = self._data.read(len(b))
        b[: len(chunk)] = chunk
        return len(chunk)


def test_non_rewindable_stream_is_not_replayed(client, api):
    route = api.post("/services/speech-to-text/recognize").mock(return_value=httpx.Response(503))
    with pytest.raises(voices_az.ServerError):
        client.stt.recognize(OneShot(b"data"), filename="a.wav", language=6, wait=False)
    assert route.call_count == 1


# --------------------------------------------------------------------------- policy unit


def test_retry_safe_flags():
    assert Call("GET", "/x").retry_safe
    assert Call("POST", "/x", idempotency_key="k").retry_safe
    assert not Call("POST", "/x").retry_safe
    assert not Call("PUT", "/x").retry_safe
    assert not Call("DELETE", "/x").retry_safe


def test_backoff_is_capped():
    assert _base.backoff_delay(20) <= 8.0 * 1.25
    err = voices_az.RateLimitError("x", status_code=429, retry_after=61)
    assert _base.backoff_delay(0, err) is None
    err = voices_az.RateLimitError("x", status_code=429, retry_after=0)
    assert _base.backoff_delay(0, err) == 0


def test_should_retry_exception_for_unknown_errors():
    assert not _base.should_retry_exception(ValueError(), Call("GET", "/"), True)
    assert not _base.should_retry_exception(httpx.ConnectError("x"), Call("GET", "/"), False)
