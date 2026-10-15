from __future__ import annotations

import io
import json

import httpx
import pytest

import voices_az
from voices_az.types import Voice

from .conftest import fail, ok, project

P = 7420
RID = "2b8e6f11-4c33-4d2a-9a6f-7c1e5d9b0a22"
XID = "5d1f7c3e-8a20-4b6d-9f11-2c7a4e0b3d99"
MP4 = "https://storage.voices.test/storage/dub/t/clean/c/dubbed.mp4?v=1757923200"
MP3 = "https://storage.voices.test/storage/dub/t/clean/c/dubbed.mp3?v=1757923200"
EXPORT = f"/services/dubbing/export/{P}"
PROJECT = f"/services/dubbing/{P}"


def body_of(request: httpx.Request) -> str:
    return request.read().decode("utf-8", "replace")


def test_create_from_file(client, api, tmp_path):
    video = tmp_path / "promo.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 1000)
    init = api.post("/services/dubbing/init").mock(return_value=ok({
        "project_id": P, "price": {"amount": "2.10", "currency": "AZN"},
        "project": project(P, 1, is_paid=False, title="promo.mp4")}))
    draft = client.dubbing.create(video, target_language=6, source_language=1,
                                  background_mode="separate", speakers=2, overlap_pan=False,
                                  auto_emotion=True)
    assert draft.project_id == P
    assert str(draft.price.amount) == "2.10"
    assert draft.project.status.id == 1 and draft.project.is_paid is False
    body = body_of(init.calls.last.request)
    assert 'name="file"; filename="promo.mp4"' in body
    assert "Content-Type: video/mp4" in body
    assert 'name="language_id"\r\n\r\n6' in body
    assert 'name="source_language_id"\r\n\r\n1' in body
    # The neutral name goes on the wire (the API accepts it since 2026-10-15).
    assert 'name="background_mode"\r\n\r\nseparate' in body
    assert 'name="num_speakers"\r\n\r\n2' in body
    assert 'name="overlap_pan"\r\n\r\n0' in body
    assert 'name="auto_emotion"\r\n\r\n1' in body
    assert init.calls.last.request.headers["Idempotency-Key"]


def test_create_from_youtube_defaults(client, api):
    init = api.post("/services/dubbing/init").mock(return_value=ok({"project_id": P}))
    draft = client.dubbing.create(youtube_url="https://www.youtube.com/watch?v=abc")
    assert draft.project is None and draft.price is None
    body = body_of(init.calls.last.request)
    assert "background_mode=duck" in body
    assert "language_id" not in body and "overlap_pan" not in body


@pytest.mark.parametrize("kwargs", [
    {"background_mode": "loud"},
    {"speakers": 0},
    {"speakers": 11},
])
def test_create_validates_locally(client, api, kwargs):
    with pytest.raises(ValueError):
        client.dubbing.create(b"x", filename="a.mp4", **kwargs)


def test_preview_generate_wait(client, api, fake_time):
    prev = api.post(f"/services/dubbing/preview/{P}").mock(return_value=ok({
        "request_id": RID, "previews_used": 1, "free_previews": 3, "price": None}))
    run = client.dubbing.preview(P, target_language=6, speakers=2)
    assert run.request_id == RID
    assert run.previews_used == 1 and run.free_previews == 3 and run.price is None
    assert json.loads(prev.calls.last.request.content) == {"language_id": 6,
                                                           "num_speakers": 2}
    assert prev.calls.last.request.headers["Idempotency-Key"]

    gen = api.post(f"/services/dubbing/generate/{P}").mock(return_value=ok({"request_id": RID}))
    run = client.dubbing.generate(P, target_language=6, auto_emotion=False, voice_map={
        "SPEAKER_00": 41,
        "SPEAKER_01": Voice.from_dict({"id": 58}),
        "SPEAKER_02": {"voice_id": 7},
    })
    assert run.request_id == RID
    assert json.loads(gen.calls.last.request.content) == {
        "language_id": 6, "auto_emotion": False,
        "voice_map": {"SPEAKER_00": {"voice_id": 41}, "SPEAKER_01": {"voice_id": 58},
                      "SPEAKER_02": {"voice_id": 7}},
    }

    api.get(f"/services/dubbing/get-response/{RID}").mock(side_effect=[
        ok({"status": "IN_PROGRESS", "stage": "translating", "percentage": 38,
            "video_url": None, "audio_url": None}),
        ok({"status": "COMPLETED", "stage": "done", "percentage": 100, "video_url": None,
            "audio_url": "https://storage.voices.test/dub/dubbed.mp3", "duration_ms": 92400,
            "source_lang": "en", "speakers": [{"key": "SPEAKER_00"}]}),
    ])
    stages = []
    status = client.dubbing.wait(RID, on_progress=lambda s: stages.append(s.stage))
    assert status.is_completed and not status.is_failed
    assert status.duration_ms == 92400 and status.source_lang == "en"
    assert status.speakers == [{"key": "SPEAKER_00"}]
    assert stages == ["translating", "done"]
    assert fake_time.sleeps == [2.0]


def test_bad_voice_map(client):
    with pytest.raises(ValueError):
        client.dubbing.generate(P, voice_map={"SPEAKER_00": {"voice": 1}})


def test_failed_run(client, api):
    api.get(f"/services/dubbing/get-response/{RID}").mock(return_value=ok({"status": "FAILED"}))
    with pytest.raises(voices_az.JobFailedError) as exc:
        client.dubbing.wait(RID)
    assert exc.value.request_id == RID


def test_get_response(client, api):
    api.get(f"/services/dubbing/get-response/{RID}").mock(return_value=ok({
        "status": "IN_PROGRESS", "percentage": 0}))
    status = client.dubbing.get_response(RID)
    assert status.status == "IN_PROGRESS" and status.percentage == 0


def test_render_and_regenerate_chunk(client, api):
    api.post(f"/services/dubbing/render/{P}").mock(return_value=ok({
        "request_id": RID, "renders_used": 4, "free_renders": 3,
        "price": {"amount": "0.20", "currency": "AZN"}}))
    run = client.dubbing.render(P)
    assert run.renders_used == 4 and str(run.price.amount) == "0.20"

    regen = api.post(f"/services/dubbing/regenerate-chunk/{P}/c1").mock(return_value=ok({
        "request_id": RID, "price": {"amount": "0.05", "currency": "AZN"},
        "chunk": {"id": "c1"}}))
    run = client.dubbing.regenerate_chunk(P, "c1", idempotency_key="regen-c1")
    assert run.chunk == {"id": "c1"}
    assert regen.calls.last.request.headers["Idempotency-Key"] == "regen-c1"


def test_export_ready(client, api):
    route = api.post(EXPORT).mock(return_value=ok({"title": "promo.mp4", "file": MP4,
                                                   "audio": MP3}))
    exported = client.dubbing.export(P)
    assert not exported.pending
    assert exported.file == MP4 and exported.audio == MP3
    assert "Idempotency-Key" not in route.calls.last.request.headers


def test_an_audio_source_exports_and_downloads_as_mp3(client, api, tmp_path):
    api.post(EXPORT).mock(return_value=ok({"title": "talk.mp3", "file": MP3, "audio": MP3,
                                           "audio_only": True}))
    exported = client.dubbing.export(P)
    assert exported.audio_only and exported.file == MP3 and not exported.pending
    api.get(MP3).mock(return_value=httpx.Response(200, content=b"ID3"))
    saved = client.dubbing.download(P, tmp_path)
    assert saved.name == f"voices-dub-{P}.mp3" and saved.read_bytes() == b"ID3"


def test_export_reports_video(client, api):
    api.post(EXPORT).mock(return_value=ok({"title": "t", "file": MP4, "audio": MP3,
                                           "audio_only": False}))
    assert client.dubbing.export(P).audio_only is False


def test_former_background_mode_spelling_is_sent_as_separate(client, api):
    settings = api.put(f"/services/dubbing/{P}/settings").mock(return_value=ok({
        "project": project(P, 4)}))
    client.dubbing.update_settings(P, background_mode="demucs")
    assert json.loads(settings.calls.last.request.content) == {"background_mode": "separate"}


def test_export_pending(client, api):
    api.post(EXPORT).mock(return_value=ok({"pending": True, "request_id": XID}, status=202))
    exported = client.dubbing.export(P)
    assert exported.pending and exported.request_id == XID and exported.file is None


def test_export_is_not_retried(client, api):
    route = api.post(EXPORT).mock(return_value=httpx.Response(504))
    with pytest.raises(voices_az.ServerError):
        client.dubbing.export(P)
    assert route.call_count == 1


def test_download_waits_for_the_assembly(client, api, tmp_path, fake_time):
    export = api.post(EXPORT).mock(side_effect=[
        ok({"pending": True, "request_id": XID}, status=202),
        ok({"title": "promo.mp4", "file": MP4, "audio": MP3}),
    ])
    api.get(PROJECT).mock(side_effect=[
        ok({"project": project(P, 4, body={"export_status": "pending",
                                           "export_request_id": XID}), "request_id": XID}),
        ok({"project": project(P, 4, body={"export_status": None}), "request_id": XID}),
    ])
    video = api.get(MP4).mock(return_value=httpx.Response(200, content=b"mp4data"))
    audio = api.get(MP3).mock(return_value=httpx.Response(200, content=b"mp3data"))
    events = []
    path = client.dubbing.download(P, tmp_path / "dub.mp4", audio_path=tmp_path,
                                   on_progress=events.append)
    assert path == tmp_path / "dub.mp4"
    assert path.read_bytes() == b"mp4data"
    assert (tmp_path / f"voices-dub-{P}.mp3").read_bytes() == b"mp3data"
    assert export.call_count == 2
    assert [e.pending for e in events] == [True, False]
    assert fake_time.sleeps == [2.0, 2.0]
    # The ?v= cache-buster is kept exactly as given.
    assert video.calls.last.request.url.params["v"] == "1757923200"
    assert "X-API-KEY" not in audio.calls.last.request.headers


def test_download_restarts_a_failed_assembly(client, api, tmp_path):
    export = api.post(EXPORT).mock(side_effect=[
        ok({"pending": True, "request_id": XID}, status=202),
        ok({"pending": True, "request_id": "second"}, status=202),
        ok({"title": "promo.mp4", "file": MP4, "audio": MP3}),
    ])
    api.get(PROJECT).mock(side_effect=[
        ok({"project": project(P, 4, body={"export_status": "failed"})}),
        ok({"project": project(P, 4, body={"export_status": None})}),
    ])
    api.get(MP3).mock(return_value=httpx.Response(200, content=b"mp3"))
    path = client.dubbing.download(P, audio_path=tmp_path / "a.mp3")
    assert path == tmp_path / "a.mp3"
    assert export.call_count == 3


def test_download_gives_up_after_repeated_failures(client, api, tmp_path):
    api.post(EXPORT).mock(return_value=ok({"pending": True, "request_id": XID}, status=202))
    api.get(PROJECT).mock(return_value=ok({"project": project(P, 4, body={
        "export_status": "failed"})}))
    with pytest.raises(voices_az.JobFailedError) as exc:
        client.dubbing.download(P, tmp_path / "x.mp4")
    assert exc.value.status == "failed"


def test_download_times_out(client, api, tmp_path):
    api.post(EXPORT).mock(return_value=ok({"pending": True, "request_id": XID}, status=202))
    api.get(PROJECT).mock(return_value=ok({"project": project(P, 4, body={
        "export_status": "pending"})}))
    with pytest.raises(voices_az.TimeoutError) as exc:
        client.dubbing.download(P, tmp_path / "x.mp4", wait_timeout=9)
    assert exc.value.request_id == XID


def test_download_nothing_to_export(client, api, tmp_path):
    api.post(EXPORT).mock(return_value=httpx.Response(422, json={
        "status": "error", "message": "There is no rendered video to export yet.",
        "errors": {"video_url": ["There is no rendered video to export yet."]}}))
    with pytest.raises(voices_az.ValidationError) as exc:
        client.dubbing.download(P, tmp_path / "x.mp4")
    assert type(exc.value) is voices_az.ValidationError
    assert "video_url" in exc.value.errors


def test_download_requires_a_destination(client):
    with pytest.raises(ValueError):
        client.dubbing.download(P)


@pytest.mark.parametrize("payload,kwargs", [
    ({"title": "t", "file": None, "audio": MP3}, {"path": "x.mp4"}),
    ({"title": "t", "file": MP4, "audio": None}, {"audio_path": "x.mp3"}),
])
def test_download_missing_urls(client, api, tmp_path, payload, kwargs):
    api.post(EXPORT).mock(return_value=ok(payload))
    kwargs = {k: tmp_path / v for k, v in kwargs.items()}
    with pytest.raises(voices_az.VoicesError):
        client.dubbing.download(P, **kwargs)


def test_download_into_file_object(client, api):
    api.post(EXPORT).mock(return_value=ok({"title": "t", "file": MP4, "audio": MP3}))
    api.get(MP4).mock(return_value=httpx.Response(200, content=b"12345"))
    buffer = io.BytesIO()
    assert client.dubbing.download(P, buffer) == 5


def test_settings_and_chunks(client, api):
    settings = api.put(f"/services/dubbing/{P}/settings").mock(return_value=ok({
        "project": project(P, 4)}))
    assert client.dubbing.update_settings(P, background_mode="duck", overlap_pan=True).id == P
    assert json.loads(settings.calls.last.request.content) == {"background_mode": "duck",
                                                               "overlap_pan": True}

    add = api.post(f"/services/dubbing/{P}/chunk").mock(return_value=ok({
        "chunk": {"id": "new", "speaker": "SPEAKER_00"}}))
    chunk = client.dubbing.add_chunk(P, speaker="SPEAKER_00", start_ms=1200, trans="Salam",
                                     target_duration_ms=900)
    assert chunk["id"] == "new"
    assert json.loads(add.calls.last.request.content) == {
        "speaker": "SPEAKER_00", "start_ms": 1200, "trans": "Salam", "target_duration_ms": 900}

    upd = api.put(f"/services/dubbing/{P}/chunk/c1").mock(return_value=ok({"chunk": {"id": "c1"}}))
    client.dubbing.update_chunk(P, "c1", trans=None, voice=None, muted=True, volume_db=-3.5)
    assert json.loads(upd.calls.last.request.content) == {
        "trans": None, "voice": None, "muted": True, "volume_db": -3.5}
    client.dubbing.update_chunk(P, "c1", voice=58, speed=1.2, start_ms=10, speaker="S",
                                target_duration_ms=500)
    assert json.loads(upd.calls.last.request.content) == {
        "voice": {"voice_id": 58}, "speed": 1.2, "start_ms": 10, "speaker": "S",
        "target_duration_ms": 500}
    with pytest.raises(ValueError):
        client.dubbing.update_chunk(P, "c1")

    api.delete(f"/services/dubbing/{P}/chunk/c1").mock(return_value=ok({"chunk_id": "c1"}))
    assert client.dubbing.delete_chunk(P, "c1") == {"chunk_id": "c1"}


def test_catalogue_and_projects(client, api):
    api.get("/services/dubbing/get-formats").mock(return_value=ok({
        "formats": ["mp4", "mov"], "background_modes": {"duck": "Duck", "demucs": "Separate"}}))
    formats = client.dubbing.formats()
    assert formats.formats == ["mp4", "mov"] and formats.background_modes["duck"] == "Duck"

    voices = api.get("/services/dubbing/get-voices").mock(return_value=ok({"voices": [
        {"id": 41, "full_name": "Aysel", "gender": {"id": 1, "title": "Woman"},
         "languages": [{"id": 6, "code": "az", "title": "Azerbaijani"}], "favorite": False}]}))
    found = client.dubbing.voices(language=6)
    assert found[0].full_name == "Aysel" and found[0].languages[0].code == "az"
    assert voices.calls.last.request.url.params["language_id"] == "6"
    client.dubbing.voices()
    assert "language_id" not in voices.calls.last.request.url.params

    api.get("/services/dubbing/get-projects").mock(return_value=ok({"projects": {
        "data": [project(P)], "meta": {}}}))
    assert client.dubbing.list_projects().items[0].id == P

    api.get(PROJECT).mock(return_value=ok({"project": project(P, 4, body={
        "speakers": [{"key": "SPEAKER_00", "gender": "male"}], "chunks": []}),
        "request_id": RID}))
    got = client.dubbing.get_project(P)
    assert got.request_id == RID and got.body["speakers"][0]["key"] == "SPEAKER_00"

    api.put(f"/services/dubbing/update-title/{P}").mock(return_value=ok({
        "project": project(P, title="promo")}))
    assert client.dubbing.rename(P, "promo").title == "promo"
    api.delete(PROJECT).mock(return_value=ok(None))
    client.dubbing.delete_project(P)


def test_expired_project(client, api):
    api.post(f"/services/dubbing/render/{P}").mock(return_value=fail(410, "gone", data={
        "project_id": P, "expired_at": "2026-03-18T04:00:11+04:00"}))
    with pytest.raises(voices_az.ProjectExpiredError):
        client.dubbing.render(P)


def test_content_policy_on_export(client, api):
    api.post(EXPORT).mock(return_value=fail(422, "content_policy", "Refused"))
    with pytest.raises(voices_az.ContentPolicyError):
        client.dubbing.export(P)
