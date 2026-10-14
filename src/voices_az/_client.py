"""The synchronous :class:`Client` and the asynchronous :class:`AsyncClient`."""

from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, TypeVar, Union, cast

import httpx

from . import _base
from ._base import (
    Call,
    Download,
    Now,
    PreparedUpload,
    Sleep,
    backoff_delay,
    build_headers,
    handle_response,
    should_retry_exception,
    should_retry_status,
)
from .exceptions import APIConnectionError, APIStatusError, APITimeoutError
from .resources.account import Account, AsyncAccount
from .resources.catalogue import (
    AsyncLanguages,
    AsyncServices,
    AsyncVoices,
    Languages,
    Services,
    Voices,
)
from .resources.dubbing import AsyncDubbing, Dubbing
from .resources.stt import STT, AsyncSTT
from .resources.tts import TTS, AsyncTTS
from .types import Language

__all__ = ["Client", "AsyncClient"]

T = TypeVar("T")
Op = Generator[Any, Any, T]
TimeoutTypes = Union[float, httpx.Timeout, None]


class _State:
    """Per-client caches shared by the operations."""

    def __init__(self) -> None:
        self.languages: Optional[List[Language]] = None


class _BaseClient:
    def __init__(
        self,
        api_key: Optional[str],
        base_url: Optional[str],
        timeout: TimeoutTypes,
        max_retries: int,
        language: Optional[str],
        poll_interval: float,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        self.api_key = _base.resolve_api_key(api_key)
        self.base_url = _base.resolve_base_url(base_url)
        self.timeout: Union[float, httpx.Timeout] = (
            _base.DEFAULT_TIMEOUT if timeout is None else timeout
        )
        # An explicit timeout also applies to a caller-supplied http_client.
        self._request_timeout: Any = (
            httpx.USE_CLIENT_DEFAULT if timeout is None else timeout
        )
        self.max_retries = max_retries
        self.language = _base.normalize_language(language)
        self.poll_interval = max(float(poll_interval), _base.MIN_POLL_INTERVAL)
        self._state = _State()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(base_url={self.base_url!r})"

    def _build_request(self, http: httpx.Client | httpx.AsyncClient, call: Call,
                       files: Optional[List[Any]]) -> httpx.Request:
        params = _drop_none(call.params) if call.params else None
        headers = build_headers(self.api_key, self.language, call)
        url = self.base_url + call.path
        if call.uploads or call.form is not None:
            data = {k: _base.form_value(v) for k, v in _drop_none(call.form or {}).items()}
            return http.build_request(call.method, url, params=params, data=data,
                                      files=files or None, headers=headers,
                                      timeout=self._request_timeout)
        body = call.json if call.keep_none else _drop_none(call.json)
        return http.build_request(call.method, url, params=params, json=body, headers=headers,
                                  timeout=self._request_timeout)

    @staticmethod
    def _wrap_transport_error(exc: httpx.TransportError) -> APIConnectionError:
        if isinstance(exc, httpx.TimeoutException):
            return APITimeoutError(request=_request_of(exc))
        return APIConnectionError(f"Could not reach the Voices.az API: {exc}",
                                  request=_request_of(exc))


class Client(_BaseClient):
    """Synchronous client for the Voices.az API.

    Args:
        api_key: The account's API key. Defaults to the ``VOICES_API_KEY`` environment
            variable. Find it in the panel at app.voices.az -> Profile -> API key.
        base_url: API root, ``https://voices.az/api`` by default (or ``VOICES_BASE_URL``).
        timeout: HTTP timeout in seconds or an :class:`httpx.Timeout`. Default: 120 s
            (10 s to connect).
        max_retries: How many times a failed request is repeated when that is safe (see
            the README). ``0`` disables retries.
        language: ``az``, ``en``, ``ru`` or ``tr`` - language of the API's human-readable
            messages (``Accept-Language``). Ids and enum values are not affected.
        poll_interval: Seconds between status polls in the ``wait`` helpers (at least 2,
            as the API asks).
        http_client: An :class:`httpx.Client` to use instead of the client's own (for
            proxies, custom TLS, ...). It is not closed by :meth:`close`.

    Use it as a context manager, or call :meth:`close` when done::

        with voices_az.Client() as client:
            print(client.account.balance())
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        timeout: TimeoutTypes = None,
        max_retries: int = _base.DEFAULT_MAX_RETRIES,
        language: Optional[str] = None,
        poll_interval: float = _base.MIN_POLL_INTERVAL,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        super().__init__(api_key, base_url, timeout, max_retries, language, poll_interval)
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(timeout=self.timeout)
        self._sleep: Callable[[float], None] = time.sleep
        self._clock: Callable[[], float] = time.monotonic

        self.tts = TTS(self)
        self.stt = STT(self)
        self.dubbing = Dubbing(self)
        self.voices = Voices(self)
        self.languages = Languages(self)
        self.services = Services(self)
        self.account = Account(self)

    # -- lifecycle
    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- low level
    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Call any endpoint and return the envelope's ``data``.

        ``path`` is relative to ``base_url`` (``"/services"``). Accepts ``params``,
        ``json``, ``form`` and ``idempotency_key``. Errors are raised as with every other
        method. Use it for endpoints this version does not wrap yet.
        """
        return self._call(Call(method.upper(), path, **kwargs))

    def _run(self, op: Op[T]) -> T:
        try:
            command = next(op)
        except StopIteration as stop:
            return cast(T, stop.value)
        while True:
            try:
                result = self._execute(command)
            except Exception as exc:  # handed to the operation, which may handle it
                try:
                    command = op.throw(exc)
                except StopIteration as stop:
                    return cast(T, stop.value)
                continue
            try:
                command = op.send(result)
            except StopIteration as stop:
                return cast(T, stop.value)

    def _execute(self, command: Any) -> Any:
        if isinstance(command, Call):
            return self._call(command)
        if isinstance(command, Sleep):
            self._sleep(command.seconds)
            return None
        if isinstance(command, Now):
            return self._clock()
        if isinstance(command, Download):
            return self._download(command)
        raise TypeError(f"Unknown command {command!r}")  # pragma: no cover

    def _call(self, call: Call) -> Any:
        uploads = [PreparedUpload(u) for u in call.uploads]
        replayable = all(u.replayable for u in uploads)
        attempt = 0
        while True:
            try:
                files = [u.open() for u in uploads]
                request = self._build_request(self._http, call, files)
                response = self._http.send(request)
            except httpx.TransportError as exc:
                if attempt < self.max_retries and should_retry_exception(exc, call, replayable):
                    self._sleep(backoff_delay(attempt) or 0.0)
                    attempt += 1
                    continue
                raise self._wrap_transport_error(exc) from exc
            finally:
                for u in uploads:
                    u.close()
            try:
                return handle_response(response, call)
            except APIStatusError as error:
                if attempt < self.max_retries and should_retry_status(error, call, replayable):
                    delay = backoff_delay(attempt, error)
                    if delay is not None:
                        self._sleep(delay)
                        attempt += 1
                        continue
                raise

    def _download(self, command: Download) -> Any:
        attempt = 0
        to_path = not hasattr(command.dest, "write")
        while True:
            try:
                with self._http.stream("GET", command.url, headers=_download_headers(),
                                       follow_redirects=True) as response:
                    if response.status_code >= 400:
                        response.read()
                        raise _download_error(response)
                    if to_path:
                        with _AtomicFile(command.dest) as out:
                            for chunk in response.iter_bytes():
                                out.write(chunk)
                        return out.path
                    written = 0
                    for chunk in response.iter_bytes():
                        command.dest.write(chunk)  # type: ignore[union-attr]
                        written += len(chunk)
                    return written
            except httpx.TransportError as exc:
                if to_path and attempt < self.max_retries:
                    self._sleep(backoff_delay(attempt) or 0.0)
                    attempt += 1
                    continue
                raise self._wrap_transport_error(exc) from exc


class AsyncClient(_BaseClient):
    """Asynchronous client for the Voices.az API. Same surface as :class:`Client`, with
    every method awaitable::

        async with voices_az.AsyncClient() as client:
            result = await client.tts.synthesize("Salam!", voice=41)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        timeout: TimeoutTypes = None,
        max_retries: int = _base.DEFAULT_MAX_RETRIES,
        language: Optional[str] = None,
        poll_interval: float = _base.MIN_POLL_INTERVAL,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        super().__init__(api_key, base_url, timeout, max_retries, language, poll_interval)
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=self.timeout)
        self._sleep: Callable[[float], Any] = asyncio.sleep
        self._clock: Callable[[], float] = time.monotonic

        self.tts = AsyncTTS(self)
        self.stt = AsyncSTT(self)
        self.dubbing = AsyncDubbing(self)
        self.voices = AsyncVoices(self)
        self.languages = AsyncLanguages(self)
        self.services = AsyncServices(self)
        self.account = AsyncAccount(self)

    async def close(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> AsyncClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Async version of :meth:`Client.request`."""
        return await self._call(Call(method.upper(), path, **kwargs))

    async def _run(self, op: Op[T]) -> T:
        try:
            command = next(op)
        except StopIteration as stop:
            return cast(T, stop.value)
        while True:
            try:
                result = await self._execute(command)
            except Exception as exc:
                try:
                    command = op.throw(exc)
                except StopIteration as stop:
                    return cast(T, stop.value)
                continue
            try:
                command = op.send(result)
            except StopIteration as stop:
                return cast(T, stop.value)

    async def _execute(self, command: Any) -> Any:
        if isinstance(command, Call):
            return await self._call(command)
        if isinstance(command, Sleep):
            await self._sleep(command.seconds)
            return None
        if isinstance(command, Now):
            return self._clock()
        if isinstance(command, Download):
            return await self._download(command)
        raise TypeError(f"Unknown command {command!r}")  # pragma: no cover

    async def _call(self, call: Call) -> Any:
        uploads = [PreparedUpload(u) for u in call.uploads]
        replayable = all(u.replayable for u in uploads)
        attempt = 0
        while True:
            try:
                files = [u.open() for u in uploads]
                request = self._build_request(self._http, call, files)
                response = await self._http.send(request)
            except httpx.TransportError as exc:
                if attempt < self.max_retries and should_retry_exception(exc, call, replayable):
                    await self._sleep(backoff_delay(attempt) or 0.0)
                    attempt += 1
                    continue
                raise self._wrap_transport_error(exc) from exc
            finally:
                for u in uploads:
                    u.close()
            try:
                return handle_response(response, call)
            except APIStatusError as error:
                if attempt < self.max_retries and should_retry_status(error, call, replayable):
                    delay = backoff_delay(attempt, error)
                    if delay is not None:
                        await self._sleep(delay)
                        attempt += 1
                        continue
                raise

    async def _download(self, command: Download) -> Any:
        attempt = 0
        to_path = not hasattr(command.dest, "write")
        while True:
            try:
                async with self._http.stream("GET", command.url, headers=_download_headers(),
                                             follow_redirects=True) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        raise _download_error(response)
                    if to_path:
                        with _AtomicFile(command.dest) as out:
                            async for chunk in response.aiter_bytes():
                                out.write(chunk)
                        return out.path
                    written = 0
                    async for chunk in response.aiter_bytes():
                        command.dest.write(chunk)  # type: ignore[union-attr]
                        written += len(chunk)
                    return written
            except httpx.TransportError as exc:
                if to_path and attempt < self.max_retries:
                    await self._sleep(backoff_delay(attempt) or 0.0)
                    attempt += 1
                    continue
                raise self._wrap_transport_error(exc) from exc


# --------------------------------------------------------------------------- helpers


def _drop_none(mapping: Any) -> Any:
    if not isinstance(mapping, dict):
        return mapping
    return {k: v for k, v in mapping.items() if v is not None}


def _request_of(exc: httpx.TransportError) -> Optional[httpx.Request]:
    try:
        return exc.request
    except RuntimeError:  # pragma: no cover - request not attached
        return None


def _download_headers() -> Dict[str, str]:
    # Never the API key: file urls point at the storage host, not at the API.
    return {"User-Agent": _base.user_agent()}


def _download_error(response: httpx.Response) -> APIStatusError:
    return APIStatusError(
        f"Could not download the file (HTTP {response.status_code}).",
        status_code=response.status_code,
        response=response,
    )


class _AtomicFile:
    """Writes to a temporary file next to ``dest`` and moves it into place on success,
    so an interrupted download never leaves a truncated file under the final name."""

    def __init__(self, dest: Any) -> None:
        self.path = Path(os.fspath(dest))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, self._tmp = tempfile.mkstemp(prefix=".voices-", suffix=".part",
                                         dir=str(self.path.parent))
        self._fh = os.fdopen(fd, "wb")

    def write(self, chunk: bytes) -> None:
        self._fh.write(chunk)

    def __enter__(self) -> _AtomicFile:
        return self

    def __exit__(self, exc_type: Any, *rest: Any) -> None:
        self._fh.close()
        if exc_type is None:
            os.replace(self._tmp, self.path)
        else:
            with contextlib.suppress(OSError):
                os.unlink(self._tmp)
