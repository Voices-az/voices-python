"""Text-to-speech: ``client.tts``."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Union

from .._base import Call, Download
from ..types import ExportedFile, JobStatus, Page, Project, Synthesis, TTSBlock
from ._common import (
    _UNSET,
    AsyncResource,
    DestInput,
    LanguageInput,
    Op,
    ProgressCallback,
    SyncResource,
    VoiceInput,
    delete_project_op,
    destination,
    interval_of,
    new_idempotency_key,
    poll_op,
    project_from,
    project_list_op,
    project_op,
    rename_op,
    resolve_language,
    seg,
    voice_id_of,
)

__all__ = ["TTS", "AsyncTTS"]

SERVICE = "text-to-speech"
DEFAULT_WAIT_TIMEOUT = 600.0
Speed = Union[int, float]


def _speed(value: Optional[Speed]) -> Optional[Union[int, float]]:
    if value is None:
        return None
    number = float(value)
    return int(number) if number.is_integer() else number


def _strength(value: Optional[int]) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("emotion_strength must be 1, 2 or 3")
    return int(value)


def _get_response_op(request_id: str, project_id: Optional[int] = None) -> Op[Synthesis]:
    data = yield Call("GET", f"/services/{SERVICE}/get-response/{seg(request_id)}")
    return Synthesis.from_response(request_id, data if isinstance(data, Mapping) else {},
                                   project_id)


def _wait_op(request_id: str, project_id: Optional[int], interval: float,
             timeout: Optional[float], on_progress: Optional[ProgressCallback],
             delay_first: bool = False) -> Op[Synthesis]:
    def fetch() -> Call:
        return Call("GET", f"/services/{SERVICE}/get-response/{seg(request_id)}")

    def parse(data: Any) -> Synthesis:
        return Synthesis.from_response(request_id, data if isinstance(data, Mapping) else {},
                                       project_id)

    result = yield from poll_op(
        fetch, parse, lambda s: s.status == JobStatus.COMPLETED,
        lambda s: s.status == JobStatus.FAILED,
        interval=interval, timeout=timeout, on_progress=on_progress, what="synthesis",
        request_id=request_id, project_id=project_id, delay_first=delay_first,
    )
    return result


def _synthesize_op(state: Any, text: str, voice: Optional[VoiceInput],
                   language: Optional[LanguageInput], speed: Optional[Speed], wait: bool,
                   interval: float, timeout: Optional[float],
                   on_progress: Optional[ProgressCallback],
                   idempotency_key: Optional[str], emotion: Optional[str] = None,
                   emotion_strength: Optional[int] = None) -> Op[Synthesis]:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")
    strength = _strength(emotion_strength)
    language_id = yield from resolve_language(state, language)
    data = yield Call(
        "POST", f"/services/{SERVICE}/synthesize",
        json={"text": text, "language_id": language_id, "voice_id": voice_id_of(voice),
              "speed": _speed(speed), "emotion": emotion, "emotion_strength": strength},
        idempotency_key=new_idempotency_key(idempotency_key),
    )
    data = data if isinstance(data, Mapping) else {}
    request_id = str(data.get("request_id") or "")
    project = data.get("project")
    project_id = int(project) if isinstance(project, (int, str)) and str(project).isdigit() \
        else None
    if not wait:
        return Synthesis(request_id=request_id, status=JobStatus.IN_PROGRESS,
                         project_id=project_id, percentage=0, raw=dict(data))
    result = yield from _wait_op(request_id, project_id, interval, timeout, on_progress,
                                 delay_first=True)
    return result


def _add_block_op(state: Any, text: Optional[str], project_id: Optional[int],
                  voice: Optional[VoiceInput], language: Optional[LanguageInput],
                  speed: Optional[Speed], emotion: Optional[str] = None,
                  emotion_strength: Optional[int] = None) -> Op[TTSBlock]:
    strength = _strength(emotion_strength)
    language_id = yield from resolve_language(state, language)
    data = yield Call("POST", f"/services/{SERVICE}/add-block", json={
        "project_id": project_id, "text": text, "voice_id": voice_id_of(voice),
        "language_id": language_id, "speed": _speed(speed), "emotion": emotion,
        "emotion_strength": strength,
    })
    return TTSBlock.from_dict(data if isinstance(data, Mapping) else {})


def _update_block_op(project_id: int, block_id: str, text: str, speed: Speed,
                     voice: Optional[VoiceInput], emotion: Any = _UNSET,
                     emotion_strength: Optional[int] = None) -> Op[Dict[str, Any]]:
    fields: Dict[str, Any] = {"text": text, "speed": _speed(speed)}
    voice_id = voice_id_of(voice)
    if voice_id is not None:
        fields["voice_id"] = voice_id
    if emotion is not _UNSET:
        # None (or "") is sent as null: the API removes the block's emotion.
        fields["emotion"] = emotion if emotion else None
    strength = _strength(emotion_strength)
    if strength is not None:
        fields["emotion_strength"] = strength
    data = yield Call("PUT", f"/services/{SERVICE}/{int(project_id)}/{seg(block_id)}",
                      json=fields, keep_none=True)
    block = data.get("block") if isinstance(data, Mapping) else None
    return dict(block) if isinstance(block, Mapping) else {}


def _sort_blocks_op(project_id: int, block_ids: Sequence[str]) -> Op[Optional[Project]]:
    ids = [str(b) for b in block_ids]
    if not ids:
        raise ValueError("block_ids must name at least one block")
    data = yield Call("POST", f"/services/{SERVICE}/sort/{int(project_id)}",
                      json={"sort_data": ids})
    return project_from(data) if isinstance(data, Mapping) and data.get("project") else None


def _duplicate_block_op(project_id: int, block_id: str) -> Op[Dict[str, Any]]:
    data = yield Call("PUT",
                      f"/services/{SERVICE}/duplicate-block/{int(project_id)}/{seg(block_id)}")
    block = data.get("block") if isinstance(data, Mapping) else None
    return dict(block) if isinstance(block, Mapping) else {}


def _delete_block_op(project_id: int, block_id: str) -> Op[None]:
    yield Call("DELETE", f"/services/{SERVICE}/{int(project_id)}/{seg(block_id)}")
    return None


def _generate_op(project_id: int, wait: bool, interval: float, timeout: Optional[float],
                 on_progress: Optional[ProgressCallback],
                 idempotency_key: Optional[str]) -> Op[Synthesis]:
    data = yield Call("POST", f"/services/{SERVICE}/generate/{int(project_id)}",
                      idempotency_key=new_idempotency_key(idempotency_key))
    data = data if isinstance(data, Mapping) else {}
    request_id = str(data.get("request_id") or "")
    if not wait:
        return Synthesis(request_id=request_id, status=JobStatus.IN_PROGRESS,
                         project_id=int(project_id), percentage=0, raw=dict(data))
    result = yield from _wait_op(request_id, int(project_id), interval, timeout, on_progress,
                                 delay_first=True)
    return result


def _export_op(project_id: int) -> Op[ExportedFile]:
    # Never retried automatically: the API charges here and does not honour an
    # Idempotency-Key on this endpoint.
    data = yield Call("POST", f"/services/{SERVICE}/export/{int(project_id)}")
    return ExportedFile.from_dict(data if isinstance(data, Mapping) else {})


def _download_op(project_id: int, path: DestInput) -> Op[Union[Path, int]]:
    exported = yield from _export_op(project_id)
    if not exported.file:
        from ..exceptions import VoicesError

        raise VoicesError(f"Project {project_id} has no audio file to download.")
    written: Union[Path, int] = yield Download(
        exported.file, destination(path, f"voices-tts-{int(project_id)}.mp3"))
    return written


# --------------------------------------------------------------------------- sync


class TTS(SyncResource):
    """``client.tts`` - text-to-speech.

    Synthesis itself is free; **the balance is charged when the audio is exported**
    (:meth:`export` / :meth:`download`), at the per-minute tariff of
    ``client.services.get("text-to-speech")``.
    """

    def synthesize(
        self,
        text: str,
        *,
        voice: Optional[VoiceInput] = None,
        language: Optional[LanguageInput] = None,
        speed: Optional[Speed] = None,
        wait: bool = True,
        poll_interval: Optional[float] = None,
        wait_timeout: Optional[float] = DEFAULT_WAIT_TIMEOUT,
        on_progress: Optional[ProgressCallback] = None,
        idempotency_key: Optional[str] = None,
        emotion: Optional[str] = None,
        emotion_strength: Optional[int] = None,
    ) -> Synthesis:
        """Synthesize ``text`` and (by default) wait for the result.

        Creates a project, queues the synthesis and polls it until it is ``COMPLETED``.
        The returned :class:`~voices_az.types.Synthesis` carries ``preview_url`` - a
        listening copy - and ``project_id``. Nothing is charged here: to get the
        downloadable file, call :meth:`download` (or :meth:`export`), which charges the
        balance.

        Args:
            text: Up to 7000 characters. May contain the inline tags ``[PAUSE=1.5]``,
                ``[LAUGH]``, ``[SIGH]``, ``[UHM]``, ``[SHH]``.
            voice: Voice id (or a :class:`~voices_az.types.Voice`) from
                ``client.voices.list()``. Defaults to a public voice of the language.
            language: Language id or code (``"az"``, ``"en"``, ``"ru"``, ``"tr"``, ...).
            speed: ``1``, ``1.5``, ``2``, ``2.5`` or ``3``.
            wait: ``False`` returns right after queueing (``status == "IN_PROGRESS"``);
                use :meth:`wait` later.
            poll_interval: Seconds between polls (at least 2).
            wait_timeout: Give up waiting after this many seconds
                (:class:`voices_az.TimeoutError`); ``None`` waits indefinitely.
            on_progress: Called with every polled :class:`~voices_az.types.Synthesis`.
            idempotency_key: Sent as ``Idempotency-Key`` so a retry cannot start a second
                run. A fresh one is generated when omitted.
            emotion: Read the text with this emotion (an
                :class:`~voices_az.types.Emotion` code such as ``"sad"``). It must be one
                of the voice's ``emotions``. Not sent when omitted.
            emotion_strength: ``1`` weak (the default), ``2`` medium or ``3`` strong
                (:class:`~voices_az.types.EmotionStrength`); used together with
                ``emotion``. The price does not change.

        Raises:
            ContentPolicyError: The text was refused.
            ValidationError: For example an ``emotion`` the voice does not have (see
                ``errors["emotion"]``).
            JobFailedError: The run ended with ``FAILED``.
            TimeoutError: ``wait_timeout`` elapsed.
        """
        return self._run(_synthesize_op(
            self._client._state, text, voice, language, speed, wait,
            interval_of(poll_interval, self._poll_interval), wait_timeout, on_progress,
            idempotency_key, emotion, emotion_strength,
        ))

    def get_response(self, request_id: str) -> Synthesis:
        """The current state of a run (``GET .../get-response/{requestId}``).

        An unknown id - or one that belongs to another account - reads as
        ``IN_PROGRESS`` at 0 %.
        """
        return self._run(_get_response_op(request_id))

    def wait(
        self,
        request_id: str,
        *,
        project_id: Optional[int] = None,
        poll_interval: Optional[float] = None,
        wait_timeout: Optional[float] = DEFAULT_WAIT_TIMEOUT,
        on_progress: Optional[ProgressCallback] = None,
    ) -> Synthesis:
        """Poll a run until it is ``COMPLETED``.

        Raises :class:`~voices_az.JobFailedError` when it fails and
        :class:`voices_az.TimeoutError` after ``wait_timeout`` seconds.
        """
        return self._run(_wait_op(request_id, project_id,
                                  interval_of(poll_interval, self._poll_interval),
                                  wait_timeout, on_progress))

    def export(self, project_id: int) -> ExportedFile:
        """**Charges the balance** for the project and returns the audio file url.

        The first export of a project charges its price (unless the account's one-time
        free download applies - then ``free`` is ``True``); exporting an already paid
        project again does not charge twice. The file is MP3.

        This call is never retried automatically.

        Raises:
            InsufficientBalanceError: The balance does not cover the price (nothing is
                charged); see ``missing``.
            ProjectExpiredError: The project's files are past their retention window.
        """
        return self._run(_export_op(project_id))

    def download(self, project_id: int, path: DestInput) -> Union[Path, int]:
        """**Charges the balance** (via :meth:`export`) and saves the MP3 to ``path``.

        ``path`` may be a file path, an existing directory (the file is named
        ``voices-tts-<project_id>.mp3``) or a binary file object. Returns the written
        :class:`~pathlib.Path`, or the number of bytes written to a file object.
        """
        return self._run(_download_op(project_id, path))

    def add_block(self, text: Optional[str] = None, *,
                  project_id: Optional[int] = None,
                  voice: Optional[VoiceInput] = None,
                  language: Optional[LanguageInput] = None,
                  speed: Optional[Speed] = None,
                  emotion: Optional[str] = None,
                  emotion_strength: Optional[int] = None) -> TTSBlock:
        """Add a text block to a project; omit ``project_id`` to start a new project.

        Build a multi-block project with this, then queue it with :meth:`generate`. Every
        block has its own voice, so one project can mix voices.

        Args:
            text: The block's text (a placeholder when omitted).
            project_id: The project to add to; ``None`` creates a new one.
            voice: A voice id or :class:`~voices_az.types.Voice` (default: the first
                public voice of the language).
            language: Language id or code such as ``"az"`` (default: Azerbaijani). When
                given together with ``voice``, the voice must speak it.
            speed: ``1``, ``1.5``, ``2``, ``2.5`` or ``3`` (default ``1``).
            emotion: Read the block with this emotion, one of the voice's ``emotions``
                (see :attr:`~voices_az.types.Voice.emotions`); default: none.
            emotion_strength: ``1`` weak (default), ``2`` medium or ``3`` strong.

        An emotion the voice does not have, or a strength outside 1-3, raises
        :class:`~voices_az.ValidationError` (``errors["emotion"]`` /
        ``errors["emotion_strength"]``).
        """
        return self._run(_add_block_op(self._client._state, text, project_id, voice,
                                       language, speed, emotion, emotion_strength))

    def update_block(self, project_id: int, block_id: str, *, text: str,
                     speed: Speed = 1, voice: Optional[VoiceInput] = None,
                     emotion: Any = _UNSET,
                     emotion_strength: Optional[int] = None) -> Dict[str, Any]:
        """Replace a block's text and speed, and its voice when ``voice`` is given (it
        keeps its voice otherwise). Returns the updated block.

        ``emotion`` sets the block's emotion; ``emotion=None`` removes it (and its
        strength); leaving it out keeps the current one. ``emotion_strength`` alone changes
        the strength of the emotion the block already has.
        """
        return self._run(_update_block_op(project_id, block_id, text, speed, voice,
                                          emotion, emotion_strength))

    def sort_blocks(self, project_id: int, block_ids: Sequence[str]) -> Optional[Project]:
        """Put the blocks in this order (block ids, first to last). Returns the project."""
        return self._run(_sort_blocks_op(project_id, block_ids))

    def duplicate_block(self, project_id: int, block_id: str) -> Dict[str, Any]:
        """Insert a copy of a block right after it. Returns the new block."""
        return self._run(_duplicate_block_op(project_id, block_id))

    def delete_block(self, project_id: int, block_id: str) -> None:
        """Delete one block of a project."""
        return self._run(_delete_block_op(project_id, block_id))

    def generate(
        self,
        project_id: int,
        *,
        wait: bool = False,
        poll_interval: Optional[float] = None,
        wait_timeout: Optional[float] = DEFAULT_WAIT_TIMEOUT,
        on_progress: Optional[ProgressCallback] = None,
        idempotency_key: Optional[str] = None,
    ) -> Synthesis:
        """Queue a multi-block project. With ``wait=True``, poll until it completes."""
        return self._run(_generate_op(project_id, wait,
                                      interval_of(poll_interval, self._poll_interval),
                                      wait_timeout, on_progress, idempotency_key))

    def list_projects(self, *, page: int = 1, title: Optional[str] = None,
                      status: Optional[int] = None,
                      language: Optional[LanguageInput] = None) -> Page[Project]:
        """The account's text-to-speech projects, 20 per page.

        ``status`` filters by :class:`~voices_az.types.ProjectStatusCode`.
        """
        return self._run(project_list_op(SERVICE, page, title, status, language,
                                         self._client._state))

    def get_project(self, project_id: int) -> Project:
        """One project, with its blocks in ``body["blocks"]``."""
        return self._run(project_op(SERVICE, project_id))

    def delete_project(self, project_id: int) -> None:
        """Delete a project."""
        return self._run(delete_project_op(SERVICE, project_id))

    def rename(self, project_id: int, title: str) -> Optional[Project]:
        """Rename a project (3-255 characters)."""
        return self._run(rename_op(SERVICE, project_id, title))


# --------------------------------------------------------------------------- async


class AsyncTTS(AsyncResource):
    """Async version of :class:`TTS`. The balance is charged on export/download."""

    async def synthesize(
        self,
        text: str,
        *,
        voice: Optional[VoiceInput] = None,
        language: Optional[LanguageInput] = None,
        speed: Optional[Speed] = None,
        wait: bool = True,
        poll_interval: Optional[float] = None,
        wait_timeout: Optional[float] = DEFAULT_WAIT_TIMEOUT,
        on_progress: Optional[ProgressCallback] = None,
        idempotency_key: Optional[str] = None,
        emotion: Optional[str] = None,
        emotion_strength: Optional[int] = None,
    ) -> Synthesis:
        """See :meth:`TTS.synthesize`."""
        return await self._run(_synthesize_op(
            self._client._state, text, voice, language, speed, wait,
            interval_of(poll_interval, self._poll_interval), wait_timeout, on_progress,
            idempotency_key, emotion, emotion_strength,
        ))

    async def get_response(self, request_id: str) -> Synthesis:
        """See :meth:`TTS.get_response`."""
        return await self._run(_get_response_op(request_id))

    async def wait(
        self,
        request_id: str,
        *,
        project_id: Optional[int] = None,
        poll_interval: Optional[float] = None,
        wait_timeout: Optional[float] = DEFAULT_WAIT_TIMEOUT,
        on_progress: Optional[ProgressCallback] = None,
    ) -> Synthesis:
        """See :meth:`TTS.wait`."""
        return await self._run(_wait_op(request_id, project_id,
                                        interval_of(poll_interval, self._poll_interval),
                                        wait_timeout, on_progress))

    async def export(self, project_id: int) -> ExportedFile:
        """**Charges the balance.** See :meth:`TTS.export`."""
        return await self._run(_export_op(project_id))

    async def download(self, project_id: int, path: DestInput) -> Union[Path, int]:
        """**Charges the balance.** See :meth:`TTS.download`."""
        return await self._run(_download_op(project_id, path))

    async def add_block(self, text: Optional[str] = None, *,
                        project_id: Optional[int] = None,
                        voice: Optional[VoiceInput] = None,
                        language: Optional[LanguageInput] = None,
                        speed: Optional[Speed] = None,
                        emotion: Optional[str] = None,
                        emotion_strength: Optional[int] = None) -> TTSBlock:
        """See :meth:`TTS.add_block`."""
        return await self._run(_add_block_op(self._client._state, text, project_id, voice,
                                             language, speed, emotion, emotion_strength))

    async def update_block(self, project_id: int, block_id: str, *, text: str,
                           speed: Speed = 1,
                           voice: Optional[VoiceInput] = None,
                           emotion: Any = _UNSET,
                           emotion_strength: Optional[int] = None) -> Dict[str, Any]:
        """See :meth:`TTS.update_block`."""
        return await self._run(_update_block_op(project_id, block_id, text, speed, voice,
                                                emotion, emotion_strength))

    async def sort_blocks(self, project_id: int,
                          block_ids: Sequence[str]) -> Optional[Project]:
        """See :meth:`TTS.sort_blocks`."""
        return await self._run(_sort_blocks_op(project_id, block_ids))

    async def duplicate_block(self, project_id: int, block_id: str) -> Dict[str, Any]:
        """See :meth:`TTS.duplicate_block`."""
        return await self._run(_duplicate_block_op(project_id, block_id))

    async def delete_block(self, project_id: int, block_id: str) -> None:
        """See :meth:`TTS.delete_block`."""
        return await self._run(_delete_block_op(project_id, block_id))

    async def generate(
        self,
        project_id: int,
        *,
        wait: bool = False,
        poll_interval: Optional[float] = None,
        wait_timeout: Optional[float] = DEFAULT_WAIT_TIMEOUT,
        on_progress: Optional[ProgressCallback] = None,
        idempotency_key: Optional[str] = None,
    ) -> Synthesis:
        """See :meth:`TTS.generate`."""
        return await self._run(_generate_op(project_id, wait,
                                            interval_of(poll_interval, self._poll_interval),
                                            wait_timeout, on_progress, idempotency_key))

    async def list_projects(self, *, page: int = 1, title: Optional[str] = None,
                            status: Optional[int] = None,
                            language: Optional[LanguageInput] = None) -> Page[Project]:
        """See :meth:`TTS.list_projects`."""
        return await self._run(project_list_op(SERVICE, page, title, status, language,
                                               self._client._state))

    async def get_project(self, project_id: int) -> Project:
        """See :meth:`TTS.get_project`."""
        return await self._run(project_op(SERVICE, project_id))

    async def delete_project(self, project_id: int) -> None:
        """See :meth:`TTS.delete_project`."""
        return await self._run(delete_project_op(SERVICE, project_id))

    async def rename(self, project_id: int, title: str) -> Optional[Project]:
        """See :meth:`TTS.rename`."""
        return await self._run(rename_op(SERVICE, project_id, title))
