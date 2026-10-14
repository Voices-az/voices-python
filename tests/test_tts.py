from __future__ import annotations

import io
import json
from decimal import Decimal

import httpx
import pytest

import voices_az
from voices_az.types import JobStatus

from .conftest import LANGUAGES, fail, ok

SYNTH = "/services/text-to-speech/synthesize"
RID = "3a13a5c3-93d0-447c-a269-54079150f793"
POLL = f"/services/text-to-speech/get-response/{RID}"
FILE_URL = "https://storage.voices.test/storage/tmp/3a13a5c3.mp3"

COMPLETED = {
    "status": "COMPLETED",
    "preview_url": "https://storage.voices.test/storage/tmp/preview.mp3",
    "duration": 7.44,
    # The API keys finished blocks by block id.
    "blocks": {"0f2c": {"start": 0, "end": 7.44, "start_ts": "00:00:0.000",
                        "end_ts": "00:00:7.440", "duration": 7.44}},
}


def test_synthesize_waits_for_the_result(client, api, fake_time):
    start = api.post(SYNTH).mock(return_value=ok({"request_id": RID, "project": 5821}))
    poll = api.get(POLL).mock(side_effect=[
        ok({"status": "IN_PROGRESS", "percentage": 10}),
        ok({"status": "IN_PROGRESS", "percentage": 60}),
        ok(COMPLETED),
    ])
    seen = []
    result = client.tts.synthesize("Salam, dünya!", voice=41, language=6, speed=1.0,
                                   on_progress=lambda s: seen.append(s.percentage))
    assert result.is_completed and not result.is_failed
    assert result.status == JobStatus.COMPLETED
    assert result.request_id == RID
    assert result.project_id == 5821
    assert result.preview_url.endswith("preview.mp3")
    assert result.duration == 7.44
    assert result.blocks[0].block_id == "0f2c"
    assert result.blocks[0].end == 7.44
    assert poll.call_count == 3
    assert seen == [10, 60, None]
    # Never polls faster than every 2 seconds, and waits before the first poll.
    assert fake_time.sleeps == [2.0, 2.0, 2.0]
    body = json.loads(start.calls.last.request.content)
    assert body == {"text": "Salam, dünya!", "language_id": 6, "voice_id": 41, "speed": 1}


def test_synthesize_resolves_language_codes_once(client, api):
    languages = api.get("/languages").mock(return_value=ok({"languages": LANGUAGES}))
    start = api.post(SYNTH).mock(return_value=ok({"request_id": RID, "project": 1}))
    client.tts.synthesize("Salam", language="AZ", wait=False)
    client.tts.synthesize("Hello", language="en", wait=False)
    assert languages.call_count == 1
    assert [json.loads(c.request.content)["language_id"] for c in start.calls] == [6, 1]
    # The languages request needs no key, but the client sends it everywhere anyway.
    assert languages.calls.last.request.headers["X-API-KEY"]


def test_language_given_as_digits_or_language_object(client, api):
    start = api.post(SYNTH).mock(return_value=ok({"request_id": RID, "project": 1}))
    lang = voices_az.types.Language.from_dict(LANGUAGES[2])
    client.tts.synthesize("a", language="6", wait=False)
    client.tts.synthesize("a", language=lang, wait=False)
    assert [json.loads(c.request.content)["language_id"] for c in start.calls] == [6, 2]


def test_unknown_language_code(client, api):
    api.get("/languages").mock(return_value=ok({"languages": LANGUAGES}))
    with pytest.raises(ValueError, match="Known codes: az, en, ru"):
        client.tts.synthesize("Salam", language="xx", wait=False)


@pytest.mark.parametrize("bad", [True, 1.5, object()])
def test_bad_language_type(client, bad):
    with pytest.raises(TypeError):
        client.tts.synthesize("Salam", language=bad, wait=False)


@pytest.mark.parametrize("bad", ["41", True])
def test_bad_voice_type(client, api, bad):
    with pytest.raises(TypeError):
        client.tts.synthesize("Salam", voice=bad, wait=False)


def test_voice_object_and_fractional_speed(client, api):
    start = api.post(SYNTH).mock(return_value=ok({"request_id": RID, "project": 1}))
    voice = voices_az.types.Voice.from_dict({"id": 58, "full_name": "Kamran"})
    client.tts.synthesize("Salam", voice=voice, speed=2.5, wait=False)
    body = json.loads(start.calls.last.request.content)
    assert body == {"text": "Salam", "voice_id": 58, "speed": 2.5}


def test_empty_text_is_refused_locally(client):
    with pytest.raises(ValueError):
        client.tts.synthesize("   ")


def test_synthesize_without_waiting(client, api):
    api.post(SYNTH).mock(return_value=ok({"request_id": RID, "project": 77}))
    result = client.tts.synthesize("Salam", wait=False)
    assert result.status == "IN_PROGRESS"
    assert result.project_id == 77
    assert result.percentage == 0


def test_failed_synthesis_raises(client, api):
    api.post(SYNTH).mock(return_value=ok({"request_id": RID, "project": 77}))
    api.get(POLL).mock(return_value=ok({"status": "FAILED"}))
    with pytest.raises(voices_az.JobFailedError) as exc:
        client.tts.synthesize("Salam")
    assert exc.value.request_id == RID
    assert exc.value.project_id == 77
    assert exc.value.status == "FAILED"
    assert exc.value.result.is_failed


def test_synthesis_timeout(client, api, fake_time):
    api.post(SYNTH).mock(return_value=ok({"request_id": RID, "project": 77}))
    poll = api.get(POLL).mock(return_value=ok({"status": "IN_PROGRESS", "percentage": 5}))
    with pytest.raises(voices_az.TimeoutError) as exc:
        client.tts.synthesize("Salam", wait_timeout=10, poll_interval=3)
    assert exc.value.request_id == RID
    assert exc.value.last.percentage == 5
    assert sum(fake_time.sleeps) <= 10
    assert poll.call_count == 3


def test_wait_without_timeout_and_with_custom_interval(client, api, fake_time):
    api.get(POLL).mock(side_effect=[ok({"status": "IN_PROGRESS"}), ok(COMPLETED)])
    result = client.tts.wait(RID, project_id=3, poll_interval=5, wait_timeout=None)
    assert result.project_id == 3 and result.is_completed
    assert fake_time.sleeps == [5.0]


def test_get_response_and_list_style_blocks(client, api):
    api.get(POLL).mock(return_value=ok({
        "status": "COMPLETED", "preview_url": "u", "duration": 1,
        "blocks": [{"block_id": "b1", "preview_url": "p", "start": 0, "end": 1,
                    "duration": 1}, "junk"]}))
    result = client.tts.get_response(RID)
    assert result.blocks[0].block_id == "b1"
    assert result.blocks[0].preview_url == "p"
    assert len(result.blocks) == 1


def test_export_charges_and_returns_the_file(client, api):
    route = api.post("/services/text-to-speech/export/5821").mock(
        return_value=ok({"title": "Bu test", "file": FILE_URL, "free": False}))
    exported = client.tts.export(5821)
    assert exported.file == FILE_URL
    assert exported.title == "Bu test"
    assert exported.free is False
    assert "Idempotency-Key" not in route.calls.last.request.headers


def test_download_saves_the_file_without_sending_the_key(client, api, tmp_path):
    api.post("/services/text-to-speech/export/5821").mock(
        return_value=ok({"title": "t", "file": FILE_URL}))
    storage = api.get(FILE_URL).mock(return_value=httpx.Response(200, content=b"ID3audio"))
    target = tmp_path / "out" / "speech.mp3"
    path = client.tts.download(5821, target)
    assert path == target
    assert target.read_bytes() == b"ID3audio"
    headers = storage.calls.last.request.headers
    assert "X-API-KEY" not in headers and "Authorization" not in headers
    assert not list(target.parent.glob("*.part"))


def test_download_into_a_directory_and_a_file_object(client, api, tmp_path):
    api.post("/services/text-to-speech/export/9").mock(
        return_value=ok({"title": "t", "file": FILE_URL}))
    api.get(FILE_URL).mock(return_value=httpx.Response(200, content=b"abc"))
    path = client.tts.download(9, tmp_path)
    assert path == tmp_path / "voices-tts-9.mp3"
    buffer = io.BytesIO()
    assert client.tts.download(9, buffer) == 3
    assert buffer.getvalue() == b"abc"


def test_download_failure_leaves_no_partial_file(client, api, tmp_path):
    api.post("/services/text-to-speech/export/9").mock(
        return_value=ok({"title": "t", "file": FILE_URL}))
    api.get(FILE_URL).mock(return_value=httpx.Response(403, text="denied"))
    with pytest.raises(voices_az.APIStatusError) as exc:
        client.tts.download(9, tmp_path / "x.mp3")
    assert exc.value.status_code == 403
    assert list(tmp_path.iterdir()) == []


def test_download_retries_network_errors_for_paths(client, api, tmp_path):
    api.post("/services/text-to-speech/export/9").mock(
        return_value=ok({"title": "t", "file": FILE_URL}))
    route = api.get(FILE_URL).mock(side_effect=[httpx.ReadError("cut"),
                                                httpx.Response(200, content=b"ok")])
    client.tts.download(9, tmp_path / "x.mp3")
    assert route.call_count == 2
    assert (tmp_path / "x.mp3").read_bytes() == b"ok"


def test_download_does_not_retry_into_a_file_object(client, api):
    api.post("/services/text-to-speech/export/9").mock(
        return_value=ok({"title": "t", "file": FILE_URL}))
    api.get(FILE_URL).mock(side_effect=httpx.ReadError("cut"))
    with pytest.raises(voices_az.APIConnectionError):
        client.tts.download(9, io.BytesIO())


def test_download_without_a_file(client, api, tmp_path):
    api.post("/services/text-to-speech/export/9").mock(return_value=ok({"title": "t",
                                                                          "file": None}))
    with pytest.raises(voices_az.VoicesError, match="no audio"):
        client.tts.download(9, tmp_path / "x.mp3")


def test_download_insufficient_balance(client, api, tmp_path):
    api.post("/services/text-to-speech/export/9").mock(return_value=httpx.Response(422, json={
        "status": "error", "message": "Low", "errors": {"balance": ["Low"]},
        "data": {"reason": "insufficient_balance", "price": "1.00", "balance": "0.10",
                 "missing": "0.90", "currency": "AZN", "project_id": 9}}))
    with pytest.raises(voices_az.InsufficientBalanceError):
        client.tts.download(9, tmp_path / "x.mp3")
    assert list(tmp_path.iterdir()) == []


def test_multi_block_project(client, api, fake_time):
    add = api.post("/services/text-to-speech/add-block").mock(side_effect=[
        ok({"id": "b1", "project_id": 5822, "text": "Bir", "sort_order": 1, "speed": 1,
            "language": LANGUAGES[0], "voice": {"id": 41, "full_name": "Aysel"}}),
        ok({"id": "b2", "project_id": 5822, "text": "Iki", "sort_order": 2, "speed": 1}),
    ])
    first = client.tts.add_block("Bir")
    second = client.tts.add_block("Iki", project_id=first.project_id)
    assert first.id == "b1" and first.language.code == "az" and first.voice["id"] == 41
    assert json.loads(add.calls[0].request.content) == {"text": "Bir"}
    assert json.loads(add.calls[1].request.content) == {"project_id": 5822, "text": "Iki"}
    assert second.sort_order == 2

    upd = api.put("/services/text-to-speech/5822/b1").mock(
        return_value=ok({"block": {"id": "b1", "text": "Bir!"}}))
    assert client.tts.update_block(5822, "b1", text="Bir!", speed=2) == {"id": "b1",
                                                                         "text": "Bir!"}
    assert json.loads(upd.calls.last.request.content) == {"text": "Bir!", "speed": 2}

    api.delete("/services/text-to-speech/5822/b2").mock(return_value=ok(None))
    assert client.tts.delete_block(5822, "b2") is None

    gen = api.post("/services/text-to-speech/generate/5822").mock(
        return_value=ok({"request_id": RID}))
    queued = client.tts.generate(5822)
    assert queued.request_id == RID and queued.status == "IN_PROGRESS"
    assert gen.calls.last.request.headers["Idempotency-Key"]

    api.get(POLL).mock(return_value=ok(COMPLETED))
    done = client.tts.generate(5822, wait=True)
    assert done.is_completed and done.project_id == 5822


def test_block_ids_are_escaped(client, api):
    route = api.delete("/services/text-to-speech/1/a b").mock(return_value=ok(None))
    client.tts.delete_block(1, "a b")
    assert route.calls.last.request.url.raw_path == b"/api/services/text-to-speech/1/a%20b"
    with pytest.raises(ValueError):
        client.tts.delete_block(1, "")


def test_projects(client, api):
    listing = api.get("/services/text-to-speech/get-projects").mock(return_value=ok({
        "projects": {
            "data": [{"id": 5821, "title": "A", "is_expired": False, "status": {"id": 4,
                                                                           "title": "Ordered"},
                      "price": {"amount": "0.04", "currency": "AZN"}, "duration": 7},
                     {"id": 5133, "title": "B", "is_expired": True,
                      "expired_at": "2026-03-18T04:00:11+04:00", "status": {"id": 4}}],
            "links": {}, "meta": {"current_page": 1, "last_page": 3, "per_page": 20,
                                  "total": 47}}}))
    page = client.tts.list_projects(status=voices_az.types.ProjectStatusCode.ORDERED)
    assert [p.id for p in page] == [5821, 5133]
    assert len(page) == 2 and page.has_more and page.total == 47
    assert page.items[0].status_code == voices_az.types.ProjectStatusCode.ORDERED
    assert page.items[0].price.amount == Decimal("0.04")
    assert page.items[1].is_expired and page.items[1].expired_at.startswith("2026")
    assert listing.calls.last.request.url.params["status"] == "4"
    assert listing.calls.last.request.url.params["page"] == "1"

    api.get("/services/text-to-speech/5821").mock(return_value=ok({
        "project": {"id": 5821, "title": "A", "status": {"id": 3, "title": "Completed"},
                    "body": {"blocks": [{"id": "b1"}]}}, "request_id": None}))
    project = client.tts.get_project(5821)
    assert project.body["blocks"][0]["id"] == "b1"
    assert project.request_id is None

    api.put("/services/text-to-speech/update-title/5821").mock(return_value=ok({
        "project": {"id": 5821, "title": "Renamed", "status": {"id": 3}}}))
    assert client.tts.rename(5821, "Renamed").title == "Renamed"

    api.delete("/services/text-to-speech/5821").mock(return_value=ok(None))
    assert client.tts.delete_project(5821) is None


def test_not_found_project(client, api):
    api.get("/services/text-to-speech/1").mock(return_value=fail(404, "not_found"))
    with pytest.raises(voices_az.NotFoundError):
        client.tts.get_project(1)
