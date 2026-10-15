"""Catalogue: languages, voices and services (with their prices)."""

from __future__ import annotations

from typing import Any, AsyncIterator, Iterator, List, Mapping, Optional, Set

from .._base import Call
from ..types import Language, Page, Service, Voice
from ._common import (
    AsyncResource,
    LanguageInput,
    Op,
    SyncResource,
    _items,
    languages_op,
    resolve_language,
)

__all__ = ["Languages", "AsyncLanguages", "Voices", "AsyncVoices", "Services", "AsyncServices"]

VOICES_PER_PAGE = 24
_GENDERS = {"female": 1, "woman": 1, "f": 1, "male": 2, "man": 2, "m": 2}


def _gender_id(gender: object) -> Optional[int]:
    if gender is None:
        return None
    if isinstance(gender, int) and not isinstance(gender, bool) and gender in (1, 2):
        return gender
    if isinstance(gender, str) and gender.strip().lower() in _GENDERS:
        return _GENDERS[gender.strip().lower()]
    raise ValueError("gender must be 'female' / 'male' (or 1 / 2)")


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _voices_page_op(state: object, page: int, language: Optional[LanguageInput],
                    gender: object, title: Optional[str]) -> Op[Page[Voice]]:
    if page < 1:
        raise ValueError("page starts at 1")
    language_id = yield from resolve_language(state, language)
    data = yield Call("GET", f"/get-voices/{int(page)}", params={
        "language_id": language_id, "gender": _gender_id(gender), "title": title,
    })
    items = [Voice.from_dict(x) for x in _items(data, "voices") if isinstance(x, Mapping)]
    meta = data.get("meta") if isinstance(data, Mapping) else None
    meta = meta if isinstance(meta, Mapping) else {}
    return Page(items=items, current_page=_int_or_none(meta.get("current_page")),
                last_page=_int_or_none(meta.get("last_page")),
                per_page=_int_or_none(meta.get("per_page")),
                total=_int_or_none(meta.get("total")),
                raw=dict(data) if isinstance(data, Mapping) else {})


def _voices_op(state: object, page: int, language: Optional[LanguageInput],
               gender: object, title: Optional[str]) -> Op[List[Voice]]:
    result = yield from _voices_page_op(state, page, language, gender, title)
    return result.items


def _fresh(result: Page[Voice], seen: Set[int]) -> List[Voice]:
    """The voices of a page not yielded yet. A page of nothing new ends the walk: older
    servers answered every page number with the first page."""
    fresh = [v for v in result.items if v.id not in seen]
    seen.update(v.id for v in fresh)
    return fresh


def _is_last(result: Page[Voice]) -> bool:
    """The server's ``meta`` when it sends one, the page size otherwise."""
    if result.last_page is not None and result.current_page is not None:
        return not result.has_more
    return len(result.items) < VOICES_PER_PAGE


def _services_op() -> Op[List[Service]]:
    data = yield Call("GET", "/services")
    return [Service.from_dict(x) for x in _items(data, "services") if isinstance(x, Mapping)]


def _service_op(slug: str) -> Op[Service]:
    data = yield Call("GET", f"/service/{slug}")
    inner = data.get("service") if isinstance(data, Mapping) and isinstance(
        data.get("service"), Mapping) else data
    return Service.from_dict(inner if isinstance(inner, Mapping) else {})


# --------------------------------------------------------------------------- sync


class Languages(SyncResource):
    """``client.languages`` - the languages the API knows."""

    def list(self, *, refresh: bool = False) -> List[Language]:
        """All supported languages (``GET /languages``).

        The list is cached on the client; ``refresh=True`` fetches it again. A language's
        ``id`` is what every ``language_id`` expects; the helpers in this package also
        accept the ``code`` (``"az"``, ``"en"``, ...).
        """
        return self._run(languages_op(self._client._state, refresh))


class Voices(SyncResource):
    """``client.voices`` - voices for text-to-speech."""

    def list(self, *, page: int = 1, language: Optional[LanguageInput] = None,
             gender: Optional[object] = None, title: Optional[str] = None) -> List[Voice]:
        """One page (24 voices) of public voices plus the account's own
        (``GET /get-voices/{page}``). :meth:`page` returns the same voices with the
        pagination figures.

        Args:
            page: Page number, from 1.
            language: Only voices that speak this language (id or code such as ``"az"``).
            gender: ``"female"`` / ``"male"`` (or ``1`` / ``2``).
            title: Substring of the voice name.
        """
        return self._run(_voices_op(self._client._state, page, language, gender, title))

    def page(self, *, page: int = 1, language: Optional[LanguageInput] = None,
             gender: Optional[object] = None, title: Optional[str] = None) -> Page[Voice]:
        """Like :meth:`list`, as a :class:`~voices_az.types.Page` (``current_page``,
        ``last_page``, ``per_page``, ``total``, ``has_more``)."""
        return self._run(_voices_page_op(self._client._state, page, language, gender, title))

    def iter(self, *, language: Optional[LanguageInput] = None,
             gender: Optional[object] = None, title: Optional[str] = None,
             max_pages: int = 100) -> Iterator[Voice]:
        """Iterate over every matching voice, fetching pages as needed."""
        seen: Set[int] = set()
        for page in range(1, max_pages + 1):
            result = self.page(page=page, language=language, gender=gender, title=title)
            fresh = _fresh(result, seen)
            if not fresh:
                return
            yield from fresh
            if _is_last(result):
                return


class Services(SyncResource):
    """``client.services`` - services and their current tariffs."""

    def list(self) -> List[Service]:
        """Every service with its per-minute price (``GET /services``)."""
        return self._run(_services_op())

    def get(self, slug: str) -> Service:
        """One service by slug (``GET /service/{slug}``), with its ``limits`` and, for
        dubbing, the extra ``prices``. Slugs: ``text-to-speech``, ``speech-to-text``,
        ``dubbing``."""
        return self._run(_service_op(slug))


# --------------------------------------------------------------------------- async


class AsyncLanguages(AsyncResource):
    """Async version of :class:`Languages`."""

    async def list(self, *, refresh: bool = False) -> List[Language]:
        """See :meth:`Languages.list`."""
        return await self._run(languages_op(self._client._state, refresh))


class AsyncVoices(AsyncResource):
    """Async version of :class:`Voices`."""

    async def list(self, *, page: int = 1, language: Optional[LanguageInput] = None,
                   gender: Optional[object] = None, title: Optional[str] = None) -> List[Voice]:
        """See :meth:`Voices.list`."""
        return await self._run(_voices_op(self._client._state, page, language, gender, title))

    async def page(self, *, page: int = 1, language: Optional[LanguageInput] = None,
                   gender: Optional[object] = None,
                   title: Optional[str] = None) -> Page[Voice]:
        """See :meth:`Voices.page`."""
        return await self._run(_voices_page_op(self._client._state, page, language, gender,
                                               title))

    async def iter(self, *, language: Optional[LanguageInput] = None,
                   gender: Optional[object] = None, title: Optional[str] = None,
                   max_pages: int = 100) -> AsyncIterator[Voice]:
        """See :meth:`Voices.iter`."""
        seen: Set[int] = set()
        for page in range(1, max_pages + 1):
            result = await self.page(page=page, language=language, gender=gender, title=title)
            fresh = _fresh(result, seen)
            if not fresh:
                return
            for voice in fresh:
                yield voice
            if _is_last(result):
                return


class AsyncServices(AsyncResource):
    """Async version of :class:`Services`."""

    async def list(self) -> List[Service]:
        """See :meth:`Services.list`."""
        return await self._run(_services_op())

    async def get(self, slug: str) -> Service:
        """See :meth:`Services.get`."""
        return await self._run(_service_op(slug))
