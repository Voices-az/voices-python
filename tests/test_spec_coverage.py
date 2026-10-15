"""Every operation of the published OpenAPI document is reachable through the client.

The table below maps each (method, path) of ``tests/fixtures/openapi.json`` to a client
call. The test fails when the spec gains an operation the client does not wrap, when the
table names one the spec does not have, or when a call does not hit its endpoint.
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, Tuple

import httpx
import pytest

from .conftest import BASE, LANGUAGES

SPEC = json.loads((Path(__file__).parent / "fixtures" / "openapi.json").read_text("utf-8"))
METHODS = {"get", "post", "put", "patch", "delete"}

P = 7420  # project id
R = "3a13a5c3-93d0-447c-a269-54079150f793"  # request id
B = "0f2c1a5e-6b2a-4e6a-9b6e-2b4d8a1c9f77"  # block / chunk id

Key = Tuple[str, str]

# Each entry calls the client; ``c`` is a Client or an AsyncClient (the result of an async
# call is awaited by the test).
OPERATIONS: Dict[Key, Callable[[Any], Any]] = {
    ("GET", "/languages"): lambda c: c.languages.list(refresh=True),
    ("GET", "/get-voices/{page}"): lambda c: c.voices.list(page=2, language=6, gender="female"),
    ("GET", "/services"): lambda c: c.services.list(),
    ("GET", "/service/{service}"): lambda c: c.services.get("dubbing"),
    ("GET", "/customer/balance"): lambda c: c.account.balance(),
    ("GET", "/customer/transactions"): lambda c: c.account.transactions(page=2),
    # text-to-speech
    ("POST", "/services/text-to-speech/synthesize"):
        lambda c: c.tts.synthesize("Salam", voice=41, language=6, wait=False),
    ("GET", "/services/text-to-speech/get-response/{requestId}"):
        lambda c: c.tts.get_response(R),
    ("POST", "/services/text-to-speech/export/{projectId}"): lambda c: c.tts.export(P),
    ("GET", "/services/text-to-speech/get-projects"):
        lambda c: c.tts.list_projects(page=1, title="x", status=3, language=6),
    ("GET", "/services/text-to-speech/{projectId}"): lambda c: c.tts.get_project(P),
    ("DELETE", "/services/text-to-speech/{projectId}"): lambda c: c.tts.delete_project(P),
    ("POST", "/services/text-to-speech/add-block"):
        lambda c: c.tts.add_block("Salam", project_id=P, voice=41, language=6, speed=1.5),
    ("PUT", "/services/text-to-speech/{projectId}/{blockId}"):
        lambda c: c.tts.update_block(P, B, text="Salam", speed=1.5, voice=41),
    ("POST", "/services/text-to-speech/sort/{projectId}"):
        lambda c: c.tts.sort_blocks(P, [B]),
    ("PUT", "/services/text-to-speech/duplicate-block/{projectId}/{blockId}"):
        lambda c: c.tts.duplicate_block(P, B),
    ("DELETE", "/services/text-to-speech/{projectId}/{blockId}"):
        lambda c: c.tts.delete_block(P, B),
    ("POST", "/services/text-to-speech/generate/{projectId}"): lambda c: c.tts.generate(P),
    ("PUT", "/services/text-to-speech/update-title/{projectId}"):
        lambda c: c.tts.rename(P, "New title"),
    # speech-to-text
    ("POST", "/services/speech-to-text/recognize"):
        lambda c: c.stt.recognize(io.BytesIO(b"RIFF"), filename="a.wav", language=6,
                                  wait=False),
    ("POST", "/services/speech-to-text/init"):
        lambda c: c.stt.upload(youtube_url="https://www.youtube.com/watch?v=abc"),
    ("POST", "/services/speech-to-text/generate/{projectId}"):
        lambda c: c.stt.generate(P, language=6, speakers=2),
    ("GET", "/services/speech-to-text/{projectId}"): lambda c: c.stt.get_project(P),
    ("DELETE", "/services/speech-to-text/{projectId}"): lambda c: c.stt.delete_project(P),
    ("PUT", "/services/speech-to-text/{projectId}/{blockId}"):
        lambda c: c.stt.update_block(P, 0, "Düzəliş"),
    ("GET", "/services/speech-to-text/get-formats"): lambda c: c.stt.formats(),
    ("POST", "/services/speech-to-text/export/{projectId}"):
        lambda c: c.stt.export(P, format="srt"),
    ("GET", "/services/speech-to-text/get-projects"): lambda c: c.stt.list_projects(),
    ("PUT", "/services/speech-to-text/update-title/{projectId}"):
        lambda c: c.stt.rename(P, "Interview"),
    # dubbing
    ("POST", "/services/dubbing/init"):
        lambda c: c.dubbing.create(youtube_url="https://www.youtube.com/watch?v=abc",
                                   target_language=6),
    ("GET", "/services/dubbing/get-formats"): lambda c: c.dubbing.formats(),
    ("GET", "/services/dubbing/get-voices"): lambda c: c.dubbing.voices(language=6),
    ("PUT", "/services/dubbing/{projectId}/settings"):
        lambda c: c.dubbing.update_settings(P, background_mode="separate"),
    ("POST", "/services/dubbing/preview/{projectId}"): lambda c: c.dubbing.preview(P),
    ("POST", "/services/dubbing/generate/{projectId}"):
        lambda c: c.dubbing.generate(P, voice_map={"SPEAKER_00": 41}),
    ("GET", "/services/dubbing/get-response/{requestId}"):
        lambda c: c.dubbing.get_response(R),
    ("GET", "/services/dubbing/{projectId}"): lambda c: c.dubbing.get_project(P),
    ("DELETE", "/services/dubbing/{projectId}"): lambda c: c.dubbing.delete_project(P),
    ("POST", "/services/dubbing/{projectId}/chunk"):
        lambda c: c.dubbing.add_chunk(P, speaker="SPEAKER_00", start_ms=0, trans="Salam"),
    ("PUT", "/services/dubbing/{projectId}/chunk/{chunkId}"):
        lambda c: c.dubbing.update_chunk(P, B, trans="Salam", voice=None),
    ("DELETE", "/services/dubbing/{projectId}/chunk/{chunkId}"):
        lambda c: c.dubbing.delete_chunk(P, B),
    ("POST", "/services/dubbing/regenerate-chunk/{projectId}/{chunkId}"):
        lambda c: c.dubbing.regenerate_chunk(P, B),
    ("POST", "/services/dubbing/render/{projectId}"): lambda c: c.dubbing.render(P),
    ("POST", "/services/dubbing/export/{projectId}"): lambda c: c.dubbing.export(P),
    ("GET", "/services/dubbing/get-projects"): lambda c: c.dubbing.list_projects(page=3),
    ("PUT", "/services/dubbing/update-title/{projectId}"):
        lambda c: c.dubbing.rename(P, "promo"),
}


def spec_operations() -> set:
    return {
        (method.upper(), path)
        for path, item in SPEC["paths"].items()
        for method in item
        if method in METHODS
    }


def template_regex(path: str) -> str:
    return "^" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape("/api" + path)) + "$"


def responder(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/languages"):
        return httpx.Response(200, json={"success": True, "data": {"languages": LANGUAGES}})
    return httpx.Response(200, json={"success": True, "message": "ok", "data": {}})


def test_spec_is_the_published_one():
    assert SPEC["servers"][0]["url"] == "https://voices.az/api"
    assert SPEC["components"]["securitySchemes"]["ApiKeyAuth"]["name"] == "X-API-KEY"


def test_table_matches_the_spec_exactly():
    in_spec = spec_operations()
    in_table = set(OPERATIONS)
    assert in_spec - in_table == set(), "operations the client does not cover"
    assert in_table - in_spec == set(), "table entries the spec does not have"


@pytest.mark.parametrize("key", sorted(OPERATIONS), ids=lambda k: f"{k[0]} {k[1]}")
def test_operation_hits_its_endpoint(key, client, api):
    method, path = key
    api.router.route(host="api.voices.test").mock(side_effect=responder)
    OPERATIONS[key](client)
    hits = [c.request for c in api.calls
            if c.request.method == method and re.match(template_regex(path),
                                                         c.request.url.path)]
    assert hits, f"{method} {path} was not called; calls: " + ", ".join(
        f"{c.request.method} {c.request.url.path}" for c in api.calls)
    request = hits[-1]
    assert request.headers["X-API-KEY"].startswith("vz_live_")
    assert "api_key" not in str(request.url) and "vz_live_" not in str(request.url)


@pytest.mark.parametrize("key", sorted(OPERATIONS), ids=lambda k: f"{k[0]} {k[1]}")
async def test_operation_hits_its_endpoint_async(key, aclient, api):
    method, path = key
    api.router.route(host="api.voices.test").mock(side_effect=responder)
    await OPERATIONS[key](aclient)
    assert any(c.request.method == method and re.match(template_regex(path), c.request.url.path)
               for c in api.calls)


def test_idempotency_key_is_sent_exactly_where_the_spec_honours_it(client, api):
    honoured = {
        (method.upper(), path)
        for path, item in SPEC["paths"].items()
        for method, op in item.items()
        if method in METHODS and any(
            p.get("$ref", "").endswith("/IdempotencyKey") for p in op.get("parameters", []))
    }
    assert len(honoured) == 10
    api.router.route(host="api.voices.test").mock(side_effect=responder)
    for key, call in OPERATIONS.items():
        start = len(api.calls)
        call(client)
        requests = [c.request for c in list(api.calls)[start:]
                    if c.request.method == key[0]
                    and re.match(template_regex(key[1]), c.request.url.path)]
        sent = "Idempotency-Key" in requests[-1].headers
        assert sent == (key in honoured), key


def test_base_url_matches_conftest():
    assert BASE.endswith("/api")
