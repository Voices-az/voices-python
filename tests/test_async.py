"""AsyncClient has the same surface and behaviour as Client."""

from __future__ import annotations

import inspect
import io

import httpx
import pytest

import voices_az
from voices_az import resources

from .conftest import BASE, LANGUAGES, fail, ok, project

PAIRS = [
    (resources.TTS, resources.AsyncTTS),
    (resources.STT, resources.AsyncSTT),
    (resources.Dubbing, resources.AsyncDubbing),
    (resources.Voices, resources.AsyncVoices),
    (resources.Languages, resources.AsyncLanguages),
    (resources.Services, resources.AsyncServices),
    (resources.Account, resources.AsyncAccount),
]


def public_methods(cls):
    return {name: member for name, member in inspect.getmembers(cls, inspect.isfunction)
            if not name.startswith("_")}


@pytest.mark.parametrize("sync_cls,async_cls", PAIRS, ids=lambda c: c.__name__)
def test_same_methods_and_signatures(sync_cls, async_cls):
    sync_methods = public_methods(sync_cls)
    async_methods = public_methods(async_cls)
    assert set(sync_methods) == set(async_methods)
    for name, func in sync_methods.items():
        afunc = async_methods[name]
        sig, asig = inspect.signature(func), inspect.signature(afunc)
        assert sig.parameters == asig.parameters, name
        assert str(sig.return_annotation) == str(asig.return_annotation).replace(
            "AsyncIterator", "Iterator"), name
        assert inspect.iscoroutinefunction(afunc) or inspect.isasyncgenfunction(afunc), name
        assert func.__doc__ and afunc.__doc__, name


def test_clients_expose_the_same_resources():
    sync = voices_az.Client(api_key="k")
    asynchronous = voices_az.AsyncClient(api_key="k")
    names = ["tts", "stt", "dubbing", "voices", "languages", "services", "account"]
    for name in names:
        sync_type = type(getattr(sync, name)).__name__
        assert type(getattr(asynchronous, name)).__name__ == "Async" + sync_type
    sync.close()
    assert inspect.signature(voices_az.Client.__init__).parameters.keys() == \
        inspect.signature(voices_az.AsyncClient.__init__).parameters.keys()


async def test_async_synthesize_waits(aclient, api, fake_time):
    api.post("/services/text-to-speech/synthesize").mock(
        return_value=ok({"request_id": "r", "project": 3}))
    api.get("/services/text-to-speech/get-response/r").mock(side_effect=[
        ok({"status": "IN_PROGRESS", "percentage": 50}),
        ok({"status": "COMPLETED", "preview_url": "https://x/p.mp3", "duration": 1.5}),
    ])
    result = await aclient.tts.synthesize("Salam")
    assert result.is_completed and result.preview_url == "https://x/p.mp3"
    assert fake_time.sleeps == [2.0, 2.0]


async def test_async_language_codes(aclient, api):
    api.get("/languages").mock(return_value=ok({"languages": LANGUAGES}))
    route = api.post("/services/text-to-speech/synthesize").mock(
        return_value=ok({"request_id": "r", "project": 3}))
    await aclient.tts.synthesize("Salam", language="ru", wait=False)
    assert b'"language_id":2' in route.calls.last.request.content.replace(b" ", b"")
    assert [x.code for x in await aclient.languages.list()] == ["az", "en", "ru"]


async def test_async_retries_and_errors(aclient, api, fake_time):
    route = api.get("/services").mock(side_effect=[
        httpx.ConnectError("down"), httpx.Response(503), ok({"services": []})])
    assert await aclient.services.list() == []
    assert route.call_count == 3

    export = api.post("/services/text-to-speech/export/1").mock(
        side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(voices_az.APITimeoutError):
        await aclient.tts.export(1)
    assert export.call_count == 1

    gone = api.post("/services/dubbing/export/1").mock(return_value=httpx.Response(502))
    with pytest.raises(voices_az.ServerError):
        await aclient.dubbing.export(1)
    assert gone.call_count == 1

    api.get("/customer/balance").mock(return_value=fail(401, "unauthenticated"))
    with pytest.raises(voices_az.AuthenticationError):
        await aclient.account.balance()


async def test_async_rate_limit_and_idempotency(aclient, api, fake_time):
    route = api.post("/services/dubbing/generate/5").mock(side_effect=[
        fail(429, "rate_limited", headers={"Retry-After": "3"}),
        fail(409, "idempotency_in_progress"),
        ok({"request_id": "r"}),
    ])
    run = await aclient.dubbing.generate(5)
    assert run.request_id == "r"
    assert len({c.request.headers["Idempotency-Key"] for c in route.calls}) == 1
    assert fake_time.sleeps[0] == 3.0


async def test_async_network_error_is_wrapped(aclient, api):
    api.get("/services").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(voices_az.APIConnectionError):
        await aclient.services.list()


async def test_async_recognize_upload(aclient, api, tmp_path):
    source = tmp_path / "a.wav"
    source.write_bytes(b"RIFF" + b"z" * 300)
    start = api.post("/services/speech-to-text/recognize").mock(side_effect=[
        httpx.Response(503), ok({"project_id": 9, "request_id": "r"})])
    api.get("/services/speech-to-text/9").mock(return_value=ok({
        "project": project(9, 3, body={"blocks": [{"id": 0, "text": "Salam"}]})}))
    transcript = await aclient.stt.recognize(source, language=6)
    assert transcript.text == "Salam"
    assert all(b"z" * 300 in c.request.read() for c in start.calls)


async def test_async_failure_and_timeout(aclient, api):
    api.get("/services/dubbing/get-response/r").mock(return_value=ok({"status": "FAILED"}))
    with pytest.raises(voices_az.JobFailedError):
        await aclient.dubbing.wait("r")
    api.get("/services/dubbing/get-response/q").mock(return_value=ok({"status": "IN_PROGRESS"}))
    with pytest.raises(voices_az.TimeoutError):
        await aclient.dubbing.wait("q", wait_timeout=5)


async def test_async_dubbing_download(aclient, api, tmp_path):
    mp4 = "https://storage.voices.test/d.mp4?v=1"
    api.post("/services/dubbing/export/5").mock(side_effect=[
        ok({"pending": True, "request_id": "x"}, status=202),
        ok({"title": "t", "file": mp4, "audio": None}),
    ])
    api.get("/services/dubbing/5").mock(return_value=ok({"project": project(5, 4, body={
        "export_status": None})}))
    api.get(mp4).mock(return_value=httpx.Response(200, content=b"video"))
    path = await aclient.dubbing.download(5, tmp_path / "out.mp4")
    assert path.read_bytes() == b"video"


async def test_async_download_variants(aclient, api, tmp_path):
    url = "https://storage.voices.test/a.mp3"
    api.post("/services/text-to-speech/export/2").mock(return_value=ok({"file": url}))
    route = api.get(url).mock(side_effect=[httpx.ReadError("cut"),
                                           httpx.Response(200, content=b"abc"),
                                           httpx.Response(200, content=b"abc"),
                                           httpx.Response(404),
                                           httpx.ReadError("cut")])
    assert (await aclient.tts.download(2, tmp_path / "a.mp3")).read_bytes() == b"abc"
    buffer = io.BytesIO()
    assert await aclient.tts.download(2, buffer) == 3
    with pytest.raises(voices_az.APIStatusError):
        await aclient.tts.download(2, tmp_path / "b.mp3")
    with pytest.raises(voices_az.APIConnectionError):
        await aclient.tts.download(2, io.BytesIO())
    assert route.call_count == 5


async def test_async_voices_iter_and_request(aclient, api):
    api.get("/get-voices/1").mock(return_value=ok({"voices": [{"id": i} for i in range(24)]}))
    api.get("/get-voices/2").mock(return_value=ok({"voices": [{"id": 24}]}))
    ids = [v.id async for v in aclient.voices.iter()]
    assert ids == list(range(25))
    api.get("/get-voices/3").mock(return_value=ok({
        "voices": [{"id": 50}], "meta": {"current_page": 3, "last_page": 3, "per_page": 24,
                                         "total": 49}}))
    page = await aclient.voices.page(page=3)
    assert page.total == 49 and not page.has_more
    api.get("/service/tts").mock(return_value=ok({"service": {"slug": "tts"}}))
    assert (await aclient.request("GET", "/service/tts"))["service"]["slug"] == "tts"


async def test_async_context_manager():
    async with voices_az.AsyncClient(api_key="k", base_url=BASE) as c:
        assert repr(c) == f"AsyncClient(base_url='{BASE}')"
    assert c._http.is_closed
