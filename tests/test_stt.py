from __future__ import annotations

import io
import json

import httpx
import pytest

import voices_az
from voices_az.types import Recognition, Transcript

from .conftest import fail, ok, project

RECOGNIZE = "/services/speech-to-text/recognize"
PROJECT = "/services/speech-to-text/6103"

BLOCKS = [
    {"id": 0, "gender": {"id": 2, "title": "Man"}, "text": "Salam, bugün hava çox gözəldir.",
     "original_text": "Salam, bugün hava çox gözəldir.", "start": 0.32, "end": 3.11,
     "duration": 2.79},
    {"id": 1, "speaker": 1, "text": "  Bəli.  ", "start": 3.5, "end": 4.0},
    {"id": 2, "text": "   ", "start": 4.0, "end": 4.1},
]


def done_project(status: int = 3) -> dict:
    return {"project": project(6103, status, body={"percentage": 100, "blocks": BLOCKS}),
            "words_count": 412}


def multipart_fields(request: httpx.Request) -> str:
    return request.read().decode("utf-8", "replace")


def test_recognize_file_and_wait(client, api, tmp_path, fake_time):
    source = tmp_path / "interview.mp3"
    source.write_bytes(b"ID3" + b"\x00" * 2048)
    start = api.post(RECOGNIZE).mock(return_value=ok({
        "project_id": 6103, "request_id": "r1", "duration": 184,
        "price": {"amount": "0.92", "currency": "AZN"}}))
    api.get(PROJECT).mock(side_effect=[
        ok({"project": project(6103, 2, body={"percentage": 40})}),
        ok(done_project()),
    ])
    progress = []
    transcript = client.stt.recognize(source, language=6, speakers=2, remove_background=True,
                                      convert_numbers=False,
                                      on_progress=lambda t: progress.append(t.percentage))
    assert isinstance(transcript, Transcript)
    assert transcript.is_completed and not transcript.is_failed
    assert transcript.project_id == 6103
    assert transcript.text == "Salam, bugün hava çox gözəldir.\nBəli."
    assert transcript.segments[0].start == 0.32
    assert transcript.segments[0].gender.title == "Man"
    assert transcript.segments[1].speaker == "1"
    assert transcript.words_count == 412
    assert transcript.language.code == "az"
    assert transcript.project.id == 6103
    assert progress == [40, 100]
    assert fake_time.sleeps == [2.0, 2.0]

    request = start.calls.last.request
    assert request.headers["Content-Type"].startswith("multipart/form-data")
    assert request.headers["Idempotency-Key"]
    body = multipart_fields(request)
    assert 'name="voice"; filename="interview.mp3"' in body
    assert "Content-Type: audio/mpeg" in body
    assert 'name="language_id"\r\n\r\n6' in body
    assert 'name="diarize"\r\n\r\n2' in body
    # Booleans travel as 1/0, which every API version accepts.
    assert 'name="remove_background"\r\n\r\n1' in body
    assert 'name="demucs"' not in body
    assert 'name="convert_numbers"\r\n\r\n0' in body
    assert "youtube_url" not in body


def test_recognize_youtube_without_waiting(client, api):
    start = api.post(RECOGNIZE).mock(return_value=ok({
        "project_id": 6104, "request_id": "r2", "duration": 60,
        "price": {"amount": "0.30", "currency": "AZN"}}))
    queued = client.stt.recognize(youtube_url="https://www.youtube.com/watch?v=abc",
                                  language=6, wait=False)
    assert isinstance(queued, Recognition)
    assert queued.project_id == 6104 and queued.request_id == "r2"
    assert str(queued.price.amount) == "0.30"
    body = start.calls.last.request.read().decode()
    assert "youtube_url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3Dabc" in body
    assert "language_id=6" in body


def test_recognize_bytes_needs_no_name(client, api):
    start = api.post(RECOGNIZE).mock(return_value=ok({"project_id": 1}))
    client.stt.recognize(b"RIFF....", language=6, wait=False)
    body = multipart_fields(start.calls.last.request)
    assert 'filename="upload.bin"' in body
    assert "application/octet-stream" in body


def test_recognize_file_object_uses_its_name(client, api, tmp_path):
    path = tmp_path / "talk.wav"
    path.write_bytes(b"RIFF")
    start = api.post(RECOGNIZE).mock(return_value=ok({"project_id": 1}))
    with open(path, "rb") as fh:
        client.stt.recognize(fh, language=6, wait=False, filename=None)
    body = multipart_fields(start.calls.last.request)
    assert 'filename="talk.wav"' in body


@pytest.mark.parametrize("kwargs,error", [
    ({}, ValueError),
    ({"file": b"x", "youtube_url": "https://youtu.be/x"}, ValueError),
    ({"file": "https://www.youtube.com/watch?v=x"}, ValueError),
    ({"file": "definitely-missing.wav"}, FileNotFoundError),
    ({"file": 42}, TypeError),
    ({"file": b"x", "speakers": 11}, ValueError),
])
def test_recognize_rejects_bad_input_before_any_request(client, api, kwargs, error):
    route = api.post(RECOGNIZE).mock(return_value=ok({"project_id": 1}))
    with pytest.raises(error):
        client.stt.recognize(language=6, wait=False, **kwargs)
    assert route.call_count == 0


def test_recognize_requires_language(client):
    with pytest.raises(ValueError, match="language"):
        client.stt.recognize(b"x", language=None)  # type: ignore[arg-type]


def test_rejected_recognition(client, api):
    api.post(RECOGNIZE).mock(return_value=ok({"project_id": 6103, "request_id": "r"}))
    api.get(PROJECT).mock(return_value=ok({"project": project(6103, 5)}))
    with pytest.raises(voices_az.JobFailedError) as exc:
        client.stt.recognize(b"x", language=6)
    assert exc.value.project_id == 6103
    assert exc.value.request_id == "r"
    assert exc.value.status == "Status"


def test_recognition_timeout(client, api):
    api.post(RECOGNIZE).mock(return_value=ok({"project_id": 6103}))
    api.get(PROJECT).mock(return_value=ok({"project": project(6103, 2)}))
    with pytest.raises(voices_az.TimeoutError) as exc:
        client.stt.recognize(b"x", language=6, wait_timeout=7)
    assert exc.value.project_id == 6103


def test_insufficient_balance_on_recognize(client, api):
    api.post(RECOGNIZE).mock(return_value=httpx.Response(422, json={
        "status": "error", "message": "Low", "errors": {"balance": ["Low"]},
        "data": {"reason": "insufficient_balance", "price": "0.92", "balance": "0.10",
                 "missing": "0.82", "currency": "AZN", "project_id": None}}))
    with pytest.raises(voices_az.InsufficientBalanceError) as exc:
        client.stt.recognize(b"x", language=6)
    assert str(exc.value.missing) == "0.82"


def test_payload_too_large(client, api):
    api.post(RECOGNIZE).mock(return_value=fail(413, "payload_too_large", "Max 100 MB"))
    with pytest.raises(voices_az.PayloadTooLargeError):
        client.stt.recognize(b"x", language=6)


def test_two_step_upload_then_generate(client, api, fake_time):
    init = api.post("/services/speech-to-text/init").mock(return_value=ok({
        "project_id": 6103, "duration": 184,
        "preview_url": "https://storage.voices.test/stt/6103/source.mp3",
        "price": {"amount": "0.92", "currency": "AZN"}}))
    uploaded = client.stt.upload(b"audio", filename="a.mp3", project_id=1)
    assert uploaded.project_id == 6103 and uploaded.duration == 184
    assert uploaded.price.currency == "AZN"
    body = multipart_fields(init.calls.last.request)
    assert 'name="project_id"\r\n\r\n1' in body
    assert init.calls.last.request.headers["Idempotency-Key"]

    gen = api.post("/services/speech-to-text/generate/6103").mock(
        return_value=ok({"request_id": "r9"}))
    assert client.stt.generate(6103, language=6, convert_numbers=True) == "r9"
    assert json.loads(gen.calls.last.request.content) == {"language_id": 6,
                                                          "convert_numbers": True}
    assert gen.calls.last.request.headers["Idempotency-Key"]

    api.get(PROJECT).mock(return_value=ok(done_project(4)))
    transcript = client.stt.wait(6103)
    assert transcript.is_completed
    assert fake_time.sleeps == []  # wait() polls at once

    assert client.stt.get_transcript(6103).segments[0].id == 0


def test_generate_requires_language(client):
    with pytest.raises(ValueError):
        client.stt.generate(1, language=None)  # type: ignore[arg-type]


def test_corrections_formats_and_export(client, api, tmp_path):
    upd = api.put("/services/speech-to-text/6103/0").mock(return_value=ok({"text": "Düz"}))
    assert client.stt.update_block(6103, 0, "Düz") == "Düz"
    assert json.loads(upd.calls.last.request.content) == {"text": "Düz"}

    api.get("/services/speech-to-text/get-formats").mock(return_value=ok({
        "formats": {"vtt": "VTT", "txt": "TXT", "srt": "SRT"}}))
    assert client.stt.formats()["srt"] == "SRT"

    url = "https://storage.voices.test/stt/x/export/y.srt"
    exp = api.post("/services/speech-to-text/export/6103").mock(
        return_value=ok({"title": "Interview", "file": url}))
    assert client.stt.export(6103, format="srt").file == url
    assert json.loads(exp.calls.last.request.content) == {"format": "srt"}

    api.get(url).mock(return_value=httpx.Response(200, content=b"1\n00:00:00,320 --> ..."))
    path = client.stt.download(6103, tmp_path, format="srt")
    assert path.name == "voices-stt-6103.srt"
    assert path.read_bytes().startswith(b"1\n")

    buffer = io.BytesIO()
    client.stt.download(6103, buffer, format="srt")
    assert buffer.getvalue()


def test_export_without_file(client, api, tmp_path):
    api.post("/services/speech-to-text/export/1").mock(return_value=ok({"title": "x"}))
    with pytest.raises(voices_az.VoicesError):
        client.stt.download(1, tmp_path / "a.txt")


def test_projects(client, api):
    api.get("/services/speech-to-text/get-projects").mock(return_value=ok({
        "projects": {"data": [project(1), project(2)],
                     "meta": {"current_page": 2, "last_page": 2, "per_page": 20,
                              "total": 22}}}))
    page = client.stt.list_projects(page=2)
    assert [p.id for p in page] == [1, 2] and not page.has_more

    api.get(PROJECT).mock(return_value=ok(done_project()))
    assert client.stt.get_project(6103).words_count == 412

    api.put("/services/speech-to-text/update-title/6103").mock(return_value=ok({
        "project": project(6103, title="Interview"), "words_count": 3}))
    assert client.stt.rename(6103, "Interview").title == "Interview"

    api.delete(PROJECT).mock(return_value=ok(None))
    client.stt.delete_project(6103)


def test_expired_project_export(client, api):
    api.post("/services/speech-to-text/export/1").mock(return_value=fail(
        410, "gone", data={"project_id": 1, "expired_at": "2026-01-01T00:00:00+04:00"}))
    with pytest.raises(voices_az.ProjectExpiredError) as exc:
        client.stt.export(1)
    assert exc.value.project_id == 1
