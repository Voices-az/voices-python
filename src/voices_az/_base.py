"""Transport-independent core: request descriptions, response decoding, error mapping and
the retry policy. The sync and async clients both drive the same operations through
these pieces, so their behaviour cannot drift apart."""

from __future__ import annotations

import contextlib
import email.utils
import io
import mimetypes
import os
import platform
import random
import time
from dataclasses import dataclass, field
from typing import IO, Any, Dict, List, Mapping, Optional, Tuple, Union

import httpx

from ._version import __version__
from .exceptions import (
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
)

DEFAULT_BASE_URL = "https://voices.az/api"
DEFAULT_TIMEOUT = httpx.Timeout(120.0, connect=10.0)
DEFAULT_MAX_RETRIES = 2
#: The API asks clients not to poll more often than once every 2 seconds.
MIN_POLL_INTERVAL = 2.0
#: A ``Retry-After`` longer than this is not waited out silently; the error is raised.
MAX_RETRY_WAIT = 60.0
SUPPORTED_LANGUAGES = ("az", "en", "ru", "tr")

FileContent = Union[str, "os.PathLike[str]", bytes, bytearray, IO[bytes]]


# --------------------------------------------------------------------------- commands
# Operations are generators that yield these commands and receive their results. The
# client that runs them decides whether that happens synchronously or with asyncio.


@dataclass
class Upload:
    """A file to send as one multipart field."""

    field: str
    content: FileContent
    filename: Optional[str] = None
    content_type: Optional[str] = None


@dataclass
class Call:
    """One API request."""

    method: str
    path: str
    params: Optional[Dict[str, Any]] = None
    json: Any = None
    form: Optional[Dict[str, Any]] = None
    uploads: List[Upload] = field(default_factory=list)
    #: Sent as ``Idempotency-Key``; set only on the calls the API documents as honouring it.
    idempotency_key: Optional[str] = None
    #: Return a :class:`Result` (status code and headers) instead of ``data`` only.
    full: bool = False
    #: Send ``None`` values of a JSON body as ``null`` (by default they are left out).
    keep_none: bool = False

    @property
    def retry_safe(self) -> bool:
        """May this request be repeated after an ambiguous failure (timeout, 502-504)?

        True for reads and for the charging calls that carry an ``Idempotency-Key``, which
        the API replays instead of running twice. Never true for anything else - in
        particular never for ``export``, which charges and does not honour the key.
        """
        return self.method.upper() in ("GET", "HEAD") or bool(self.idempotency_key)


@dataclass
class Result:
    status_code: int
    data: Any
    headers: Mapping[str, str]


@dataclass
class Sleep:
    seconds: float


@dataclass
class Now:
    """Ask the driver for the current monotonic time."""


@dataclass
class Download:
    """Fetch a file url (no API key is sent) into ``dest`` (a path or a binary file)."""

    url: str
    dest: Union[str, os.PathLike[str], IO[bytes]]


# --------------------------------------------------------------------------- options


def user_agent() -> str:
    return (
        f"voices-az-python/{__version__} (Python {platform.python_version()}; "
        f"httpx {httpx.__version__})"
    )


def resolve_api_key(api_key: Optional[str]) -> str:
    key = api_key if api_key is not None else os.environ.get("VOICES_API_KEY")
    key = (key or "").strip()
    if not key:
        from .exceptions import VoicesError

        raise VoicesError(
            "No API key. Pass api_key=... or set the VOICES_API_KEY environment variable. "
            "The key is in the panel at app.voices.az -> Profile -> API key."
        )
    return key


def resolve_base_url(base_url: Optional[str]) -> str:
    url = base_url or os.environ.get("VOICES_BASE_URL") or DEFAULT_BASE_URL
    return url.rstrip("/")


def normalize_language(language: Optional[str]) -> Optional[str]:
    if language is None:
        return None
    code = language.strip().lower().replace("_", "-").split("-")[0]
    if code not in SUPPORTED_LANGUAGES:
        raise ValueError(
            f"Unsupported language {language!r}; use one of {', '.join(SUPPORTED_LANGUAGES)}."
        )
    return code


def build_headers(api_key: str, language: Optional[str], call: Call) -> Dict[str, str]:
    headers = {
        "X-API-KEY": api_key,
        "Accept": "application/json",
        "User-Agent": user_agent(),
    }
    if language:
        headers["Accept-Language"] = language
    if call.idempotency_key:
        headers["Idempotency-Key"] = call.idempotency_key
    return headers


def form_value(value: Any) -> str:
    """Encode one multipart field the way the API's validators accept it.

    Booleans travel as ``1``/``0``: the API's boolean rule rejects ``"true"``/``"false"``
    strings in form data.
    """
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


# --------------------------------------------------------------------------- uploads


class PreparedUpload:
    """Opens an :class:`Upload` for one attempt and knows whether it can be re-sent."""

    def __init__(self, upload: Upload) -> None:
        self.upload = upload
        content = upload.content
        self.replayable = True
        if isinstance(content, (bytes, bytearray)):
            self.kind = "bytes"
        elif isinstance(content, (str, os.PathLike)):
            self.kind = "path"
            path = os.fspath(content)
            if not os.path.isfile(path):
                raise FileNotFoundError(f"No such file: {path!r}")
        elif hasattr(content, "read"):
            # httpx sends a file object from its start (it seeks to 0), so a stream can be
            # sent again only when it is seekable.
            self.kind = "stream"
            try:
                self.replayable = bool(content.seekable())
            except (AttributeError, OSError, ValueError):
                self.replayable = False
        else:
            raise TypeError(
                "A file must be a path, bytes, or a binary file object opened with 'rb'; "
                f"got {type(content).__name__}."
            )
        self._opened: List[IO[bytes]] = []

    @property
    def filename(self) -> str:
        if self.upload.filename:
            return self.upload.filename
        content = self.upload.content
        if self.kind == "path":
            return os.path.basename(os.fspath(content))  # type: ignore[arg-type]
        name = getattr(content, "name", None)
        if isinstance(name, str) and name:
            return os.path.basename(name)
        return "upload.bin"

    @property
    def content_type(self) -> str:
        if self.upload.content_type:
            return self.upload.content_type
        guessed, _ = mimetypes.guess_type(self.filename)
        return guessed or "application/octet-stream"

    def open(self) -> Tuple[str, Tuple[str, IO[bytes], str]]:
        content = self.upload.content
        if self.kind == "bytes":
            fh: IO[bytes] = io.BytesIO(bytes(content))  # type: ignore[arg-type]
        elif self.kind == "path":
            fh = open(os.fspath(content), "rb")  # type: ignore[arg-type]  # noqa: SIM115
            self._opened.append(fh)
        else:
            fh = content  # type: ignore[assignment]
        return self.upload.field, (self.filename, fh, self.content_type)

    def close(self) -> None:
        for fh in self._opened:
            with contextlib.suppress(Exception):
                fh.close()
        self._opened.clear()


# --------------------------------------------------------------------------- responses


def decode_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def parse_retry_after(value: Optional[str], now: Optional[float] = None) -> Optional[float]:
    if value is None or value.strip() == "":
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed is None:  # pragma: no cover - older Pythons return None
        return None
    current = time.time() if now is None else now
    return max(0.0, parsed.timestamp() - current)


def _error_fields(status: int, body: Any) -> Tuple[str, Optional[str], Any, Dict[str, List[str]]]:
    """(message, type, data, field_errors) from either error shape the API produces.

    * ``{"success": false, "error": {"message", "code", "type", "data"}}`` - the
      documented envelope;
    * ``{"status": "error", "message", "errors": {field: [...]}, "data"?}`` - what a
      form-validation failure (including "insufficient balance") actually returns.
    """
    message = f"HTTP {status}"
    type_: Optional[str] = None
    data: Any = None
    errors: Dict[str, List[str]] = {}
    if isinstance(body, Mapping):
        err = body.get("error")
        if isinstance(err, Mapping):
            message = str(err.get("message") or message)
            type_ = err.get("type") if isinstance(err.get("type"), str) else None
            data = err.get("data")
        elif isinstance(err, str) and err:
            message = err
        if isinstance(body.get("message"), str) and body.get("message") and not isinstance(
            err, Mapping
        ):
            message = body["message"]
        raw_errors = body.get("errors")
        if isinstance(raw_errors, Mapping):
            for key, value in raw_errors.items():
                if isinstance(value, list):
                    errors[str(key)] = [str(v) for v in value]
                elif value is not None:
                    errors[str(key)] = [str(value)]
        if data is None and "data" in body and not isinstance(err, Mapping):
            data = body.get("data")
        if type_ is None and status == 422 and (errors or body.get("status") == "error"):
            type_ = "validation_failed"
    elif isinstance(body, str) and body.strip():
        message = body.strip()[:300]
    return message, type_, data, errors


def make_error(response: httpx.Response, body: Any = None) -> APIStatusError:
    if body is None:
        body = decode_json(response)
    status = response.status_code
    if isinstance(body, Mapping) and isinstance(body.get("error"), Mapping):
        code = body["error"].get("code")
        if isinstance(code, int) and 400 <= code <= 599 and status < 400:
            status = code
    message, type_, data, errors = _error_fields(status, body)
    kwargs: Dict[str, Any] = {
        "status_code": status,
        "type": type_,
        "data": data,
        "body": body,
        "response": response,
    }
    if status == 401:
        return AuthenticationError(message, **kwargs)
    if status == 403:
        return PermissionDeniedError(message, **kwargs)
    if status == 404:
        return NotFoundError(message, **kwargs)
    if status == 409:
        if type_ == "idempotency_in_progress":
            return IdempotencyInProgressError(message, **kwargs)
        return ConflictError(message, **kwargs)
    if status == 410:
        return ProjectExpiredError(message, **kwargs)
    if status == 413:
        return PayloadTooLargeError(message, **kwargs)
    if status == 422:
        if type_ == "content_policy":
            return ContentPolicyError(message, **kwargs)
        reason = data.get("reason") if isinstance(data, Mapping) else None
        if reason == "insufficient_balance" or (
            "balance" in errors and reason in (None, "insufficient_balance")
        ):
            return InsufficientBalanceError(message, errors=errors, **kwargs)
        return ValidationError(message, errors=errors, **kwargs)
    if status == 429:
        retry_after = parse_retry_after(response.headers.get("retry-after"))
        return RateLimitError(message, retry_after=retry_after, **kwargs)
    if status == 400:
        return BadRequestError(message, **kwargs)
    if status >= 500:
        return ServerError(message, **kwargs)
    return APIStatusError(message, **kwargs)


def handle_response(response: httpx.Response, call: Call) -> Any:
    """Decode a response: the envelope's ``data`` on success, an exception otherwise."""
    body = decode_json(response)
    if 300 <= response.status_code < 400:
        location = response.headers.get("location", "")
        raise APIStatusError(
            f"Unexpected redirect to {location!r}; check base_url.",
            status_code=response.status_code, body=body, response=response,
        )
    if response.status_code >= 400:
        raise make_error(response, body)
    if isinstance(body, Mapping) and body.get("success") is False:
        raise make_error(response, body)
    data = body.get("data") if isinstance(body, Mapping) and "success" in body else body
    if call.full:
        return Result(status_code=response.status_code, data=data, headers=response.headers)
    return data


# --------------------------------------------------------------------------- retries


def should_retry_status(error: APIStatusError, call: Call, replayable: bool) -> bool:
    if not replayable:
        return False
    status = error.status_code
    if status == 429:
        # The rate limiter answers before anything runs, so nothing happened yet.
        return True
    if status == 409 and isinstance(error, IdempotencyInProgressError):
        return bool(call.idempotency_key)
    if status in (502, 503, 504):
        return call.retry_safe
    return False


def should_retry_exception(exc: Exception, call: Call, replayable: bool) -> bool:
    if not replayable:
        return False
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        # The request never reached the API.
        return True
    if isinstance(exc, httpx.TransportError):
        return call.retry_safe
    return False


def backoff_delay(attempt: int, error: Optional[APIStatusError] = None) -> Optional[float]:
    """Seconds to wait before retry number ``attempt`` (0-based), or ``None`` to give up."""
    if isinstance(error, RateLimitError) and error.retry_after is not None:
        if error.retry_after > MAX_RETRY_WAIT:
            return None
        return float(error.retry_after)
    base = min(0.5 * (2.0**attempt), 8.0)
    return base * (0.75 + random.random() * 0.5)
