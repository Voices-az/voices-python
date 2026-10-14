from __future__ import annotations

import ssl
from typing import Any, List

import httpx
import pytest
import respx

import voices_az

BASE = "https://api.voices.test/api"
API_KEY = "vz_live_" + "0" * 40


# Building a TLS context per client dominates test time; share one.
SSL_CONTEXT = ssl.create_default_context()


def ok(data: Any = None, status: int = 200, message: str = "Operation successful",
       headers: Any = None) -> httpx.Response:
    return httpx.Response(status, json={"success": True, "message": message, "data": data},
                          headers=headers)


def fail(status: int, type_: str, message: str = "Failed", data: Any = None,
         headers: Any = None) -> httpx.Response:
    return httpx.Response(status, json={
        "success": False,
        "error": {"message": message, "code": status, "type": type_, "data": data},
    }, headers=headers)


class FakeTime:
    """Deterministic clock: sleeping advances it, nothing really waits."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: List[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    async def asleep(self, seconds: float) -> None:
        self.sleep(seconds)


@pytest.fixture
def fake_time() -> FakeTime:
    return FakeTime()


@pytest.fixture
def client(fake_time: FakeTime):
    http = httpx.Client(verify=SSL_CONTEXT)
    c = voices_az.Client(api_key=API_KEY, base_url=BASE, http_client=http)
    c._sleep = fake_time.sleep
    c._clock = fake_time.clock
    yield c
    c.close()
    http.close()


@pytest.fixture
async def aclient(fake_time: FakeTime):
    http = httpx.AsyncClient(verify=SSL_CONTEXT)
    c = voices_az.AsyncClient(api_key=API_KEY, base_url=BASE, http_client=http)
    c._sleep = fake_time.asleep
    c._clock = fake_time.clock
    yield c
    await c.close()
    await http.aclose()


class Api:
    """respx router with paths relative to the API root (absolute urls pass through)."""

    def __init__(self, router: respx.MockRouter) -> None:
        self.router = router

    def route(self, method: str, path: str, **kwargs: Any) -> respx.Route:
        # Match scheme/host/path only, so query strings never get in the way.
        url = httpx.URL(path if path.startswith("http") else BASE + path)
        return self.router.route(method=method, scheme=url.scheme, host=url.host,
                                 path=url.path, **kwargs)

    def get(self, path: str, **kwargs: Any) -> respx.Route:
        return self.route("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> respx.Route:
        return self.route("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> respx.Route:
        return self.route("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> respx.Route:
        return self.route("DELETE", path, **kwargs)

    @property
    def calls(self) -> Any:
        return self.router.calls


@pytest.fixture
def api():
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        yield Api(router)


LANGUAGES = [
    {"id": 6, "code": "az", "title": "Azerbaijani"},
    {"id": 1, "code": "en", "title": "English"},
    {"id": 2, "code": "ru", "title": "Russian"},
]


def project(pid: int = 1, status: int = 3, body: Any = None, **extra: Any) -> dict:
    data = {
        "id": pid,
        "title": "Project",
        "is_favorite": False,
        "is_expired": False,
        "expired_at": None,
        "is_paid": True,
        "language": {"id": 6, "code": "az", "title": "Azerbaijani"},
        "status": {"id": status, "title": "Status"},
        "duration": 12,
        "price": {"amount": "0.30", "currency": "AZN"},
        "body": body if body is not None else {},
    }
    data.update(extra)
    return data
