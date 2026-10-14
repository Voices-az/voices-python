"""The example scripts run end to end against a mocked API."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import httpx
import pytest

from .conftest import API_KEY, BASE, LANGUAGES, ok, project

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"example_{name}", EXAMPLES / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    monkeypatch.setenv("VOICES_API_KEY", API_KEY)
    monkeypatch.setenv("VOICES_BASE_URL", BASE)
    monkeypatch.setattr("time.sleep", lambda seconds: None)


def test_tts_to_file(api, monkeypatch, tmp_path, capsys):
    api.get("/languages").mock(return_value=ok({"languages": LANGUAGES}))
    api.post("/services/text-to-speech/synthesize").mock(
        return_value=ok({"request_id": "r", "project": 5}))
    api.get("/services/text-to-speech/get-response/r").mock(return_value=ok({
        "status": "COMPLETED", "preview_url": "https://storage.voices.test/p.mp3",
        "duration": 2.5}))
    api.post("/services/text-to-speech/export/5").mock(
        return_value=ok({"title": "t", "file": "https://storage.voices.test/f.mp3"}))
    api.get("https://storage.voices.test/f.mp3").mock(
        return_value=httpx.Response(200, content=b"ID3"))
    out = tmp_path / "salam.mp3"
    monkeypatch.setattr(sys, "argv", ["tts_to_file.py", "Salam", "-o", str(out)])
    assert load("tts_to_file").main() == 0
    assert out.read_bytes() == b"ID3"
    assert "Listen: https://storage.voices.test/p.mp3" in capsys.readouterr().out


def test_transcribe_file(api, monkeypatch, tmp_path, capsys):
    source = tmp_path / "a.mp3"
    source.write_bytes(b"ID3")
    api.get("/languages").mock(return_value=ok({"languages": LANGUAGES}))
    api.post("/services/speech-to-text/recognize").mock(
        return_value=ok({"project_id": 9, "request_id": "r"}))
    api.get("/services/speech-to-text/9").mock(return_value=ok({"project": project(9, 3, body={
        "blocks": [{"id": 0, "text": "Salam", "start": 0.5, "end": 1.0}]})}))
    api.post("/services/speech-to-text/export/9").mock(
        return_value=ok({"title": "t", "file": "https://storage.voices.test/a.srt"}))
    api.get("https://storage.voices.test/a.srt").mock(
        return_value=httpx.Response(200, content=b"1\n"))
    srt = tmp_path / "a.srt"
    monkeypatch.setattr(sys, "argv", ["transcribe_file.py", str(source), "--srt", str(srt)])
    assert load("transcribe_file").main() == 0
    assert "Salam" in capsys.readouterr().out
    assert srt.exists()


def test_dub_youtube(api, monkeypatch, tmp_path):
    api.get("/languages").mock(return_value=ok({"languages": LANGUAGES}))
    api.post("/services/dubbing/init").mock(return_value=ok({
        "project_id": 7, "price": {"amount": "2.10", "currency": "AZN"}}))
    api.post("/services/dubbing/preview/7").mock(return_value=ok({"request_id": "p"}))
    api.post("/services/dubbing/generate/7").mock(return_value=ok({"request_id": "g"}))
    for rid in ("p", "g"):
        api.get(f"/services/dubbing/get-response/{rid}").mock(return_value=ok({
            "status": "COMPLETED", "audio_url": "https://storage.voices.test/x.mp3"}))
    api.post("/services/dubbing/export/7").mock(return_value=ok({
        "title": "t", "file": "https://storage.voices.test/d.mp4", "audio": None}))
    api.get("https://storage.voices.test/d.mp4").mock(
        return_value=httpx.Response(200, content=b"mp4"))
    out = tmp_path / "d.mp4"
    monkeypatch.setattr(sys, "argv", ["dub_youtube.py", "https://www.youtube.com/watch?v=x",
                                      "--preview", "--yes", "-o", str(out)])
    assert load("dub_youtube").main() == 0
    assert out.read_bytes() == b"mp4"


def test_dub_youtube_stops_without_confirmation(api, monkeypatch):
    api.get("/languages").mock(return_value=ok({"languages": LANGUAGES}))
    api.post("/services/dubbing/init").mock(return_value=ok({"project_id": 7}))
    generate = api.post("/services/dubbing/generate/7").mock(return_value=ok({}))
    monkeypatch.setattr(sys, "argv", ["dub_youtube.py", "https://www.youtube.com/watch?v=x"])
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert load("dub_youtube").main() == 0
    assert generate.call_count == 0
