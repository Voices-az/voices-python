"""Building blocks shared by the resource modules."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import (
    IO,
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Generator,
    List,
    Mapping,
    Optional,
    TypeVar,
    Union,
)
from urllib.parse import quote

from .._base import Call, FileContent, Now, Sleep, Upload
from ..exceptions import JobFailedError, TimeoutError
from ..types import Language, Page, Project, Voice

if TYPE_CHECKING:
    from .._client import AsyncClient, Client

T = TypeVar("T")
S = TypeVar("S")
Op = Generator[Any, Any, T]

LanguageInput = Union[int, str, Language]
VoiceInput = Union[int, Voice]
PathInput = Union[str, "os.PathLike[str]"]
DestInput = Union[str, "os.PathLike[str]", IO[bytes]]
ProgressCallback = Callable[[Any], None]

#: Placeholder default meaning "argument not given" where ``None`` is a real value.
_UNSET: Any = object()


class SyncResource:
    def __init__(self, client: Client) -> None:
        self._client = client

    def _run(self, op: Op[T]) -> T:
        return self._client._run(op)

    @property
    def _poll_interval(self) -> float:
        return self._client.poll_interval


class AsyncResource:
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def _run(self, op: Op[T]) -> T:
        return await self._client._run(op)

    @property
    def _poll_interval(self) -> float:
        return self._client.poll_interval


def destination(path: DestInput, default_name: str) -> DestInput:
    """``path`` itself, or ``path/default_name`` when ``path`` is an existing directory."""
    if isinstance(path, (str, os.PathLike)) and os.path.isdir(path):
        return Path(path) / default_name
    return path


def seg(value: Any) -> str:
    """One path segment, escaped (block, chunk and request ids are opaque strings)."""
    text = str(value)
    if not text:
        raise ValueError("an id must not be empty")
    return quote(text, safe="")


def new_idempotency_key(given: Optional[str]) -> str:
    """The caller's key, or a fresh uuid so a retried charging call is never charged twice."""
    return given if given else str(uuid.uuid4())


def interval_of(given: Optional[float], default: float) -> float:
    from .._base import MIN_POLL_INTERVAL

    return max(float(given), MIN_POLL_INTERVAL) if given is not None else default


# --------------------------------------------------------------------------- languages


def languages_op(state: Any, refresh: bool = False) -> Op[List[Language]]:
    if state.languages is None or refresh:
        data = yield Call("GET", "/languages")
        items = _items(data, "languages")
        state.languages = [Language.from_dict(x) for x in items if isinstance(x, Mapping)]
    return list(state.languages)


def resolve_language(state: Any, language: Optional[LanguageInput]) -> Op[Optional[int]]:
    """Language id from an id, a :class:`Language` or a code such as ``"az"``."""
    if language is None:
        return None
    if isinstance(language, Language):
        return language.id
    if isinstance(language, bool):
        raise TypeError("language must be an id, a language code or a Language")
    if isinstance(language, int):
        return language
    if isinstance(language, str):
        text = language.strip()
        if text.isdigit():
            return int(text)
        languages = yield from languages_op(state)
        code = text.lower()
        for item in languages:
            if (item.code or "").lower() == code:
                return item.id
        known = ", ".join(sorted(x.code for x in languages if x.code))
        raise ValueError(f"Unknown language code {language!r}. Known codes: {known}.")
    raise TypeError("language must be an id, a language code or a Language")


def voice_id_of(voice: Optional[VoiceInput]) -> Optional[int]:
    if voice is None:
        return None
    if isinstance(voice, Voice):
        return voice.id
    if isinstance(voice, bool) or not isinstance(voice, int):
        raise TypeError("voice must be a voice id (int) or a Voice")
    return voice


# --------------------------------------------------------------------------- sources


def source_uploads(field: str, file: Optional[FileContent], youtube_url: Optional[str],
                   filename: Optional[str]) -> List[Upload]:
    if file is None and not youtube_url:
        raise ValueError("Pass either file=... or youtube_url=....")
    if file is not None and youtube_url:
        raise ValueError("Pass either file=... or youtube_url=..., not both.")
    if file is None:
        return []
    if isinstance(file, str) and file.lower().startswith(("http://", "https://")):
        raise ValueError("file= takes a local file; pass a link as youtube_url=....")
    return [Upload(field=field, content=file, filename=filename)]


# --------------------------------------------------------------------------- lists


def _items(data: Any, key: str) -> List[Any]:
    if isinstance(data, Mapping):
        value = data.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, Mapping):
            inner = value.get("data")
            if isinstance(inner, list):
                return inner
    if isinstance(data, list):
        return data
    return []


def page_of(payload: Any, build: Callable[[Mapping[str, Any]], T]) -> Page[T]:
    """A paginated list payload (``{data, links, meta}``) as a :class:`Page`."""
    payload = payload if isinstance(payload, Mapping) else {}
    items = payload.get("data") if isinstance(payload.get("data"), list) else []
    meta = payload.get("meta") if isinstance(payload.get("meta"), Mapping) else payload

    def num(key: str) -> Optional[int]:
        value = meta.get(key)
        return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) \
            else None

    return Page(
        items=[build(x) for x in items if isinstance(x, Mapping)],
        current_page=num("current_page"),
        last_page=num("last_page"),
        per_page=num("per_page"),
        total=num("total"),
        raw=dict(payload),
    )


def project_list_op(service: str, page: int, title: Optional[str], status: Optional[int],
                    language: Optional[LanguageInput], state: Any) -> Op[Page[Project]]:
    language_id = yield from resolve_language(state, language)
    data = yield Call("GET", f"/services/{service}/get-projects", params={
        "page": page, "title": title, "status": int(status) if status is not None else None,
        "language_id": language_id,
    })
    projects = data.get("projects") if isinstance(data, Mapping) else None
    return page_of(projects, Project.from_dict)


def project_op(service: str, project_id: int) -> Op[Project]:
    data = yield Call("GET", f"/services/{service}/{int(project_id)}")
    return project_from(data)


def project_from(data: Any) -> Project:
    data = data if isinstance(data, Mapping) else {}
    project = data.get("project") if isinstance(data.get("project"), Mapping) else data
    return Project.from_dict(project, request_id=data.get("request_id"),
                             words_count=data.get("words_count"))


def maybe_project(data: Any) -> Optional[Project]:
    if isinstance(data, Mapping) and isinstance(data.get("project"), Mapping):
        return project_from(data)
    return None


def delete_project_op(service: str, project_id: int) -> Op[None]:
    yield Call("DELETE", f"/services/{service}/{int(project_id)}")
    return None


def rename_op(service: str, project_id: int, title: str) -> Op[Optional[Project]]:
    data = yield Call("PUT", f"/services/{service}/update-title/{int(project_id)}",
                      json={"title": title})
    return maybe_project(data)


# --------------------------------------------------------------------------- polling


def poll_op(
    fetch: Callable[[], Call],
    parse: Callable[[Any], S],
    is_done: Callable[[S], bool],
    is_failed: Callable[[S], bool],
    *,
    interval: float,
    timeout: Optional[float],
    on_progress: Optional[ProgressCallback],
    what: str,
    request_id: Optional[str] = None,
    project_id: Optional[int] = None,
    delay_first: bool = False,
) -> Op[S]:
    """Poll ``fetch`` every ``interval`` seconds until the parsed state is done or failed.

    Raises :class:`JobFailedError` on failure and :class:`TimeoutError` once ``timeout``
    seconds have passed without a final state. ``timeout=None`` waits indefinitely.
    """
    started = yield Now()
    last: Optional[S] = None
    if delay_first:
        yield Sleep(interval)
    while True:
        data = yield fetch()
        last = parse(data)
        if on_progress is not None:
            on_progress(last)
        if is_failed(last):
            raise JobFailedError(
                f"The {what} failed.", request_id=request_id, project_id=project_id,
                status=_status_text(last), result=last,
            )
        if is_done(last):
            return last
        now = yield Now()
        if timeout is not None and (now - started) + interval > timeout:
            raise TimeoutError(
                f"The {what} did not finish within {timeout:g} seconds; it is still running "
                "on the server and can be waited for again.",
                request_id=request_id, project_id=project_id, last=last,
            )
        yield Sleep(interval)


def _status_text(state: Any) -> Optional[str]:
    status = getattr(state, "status", None)
    if isinstance(status, str):
        return status
    title = getattr(status, "title", None)
    return title if isinstance(title, str) else None


def form_bool(value: Optional[bool]) -> Optional[bool]:
    return None if value is None else bool(value)


def json_body(**fields: Any) -> Dict[str, Any]:
    return {k: v for k, v in fields.items() if v is not None}
