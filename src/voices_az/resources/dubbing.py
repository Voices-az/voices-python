"""Video dubbing: ``client.dubbing``."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Union

from .._base import Call, Download, FileContent, Now, Sleep
from ..exceptions import JobFailedError, TimeoutError, VoicesError
from ..types import (
    DubbingDraft,
    DubbingExport,
    DubbingFormats,
    DubbingRun,
    DubbingStatus,
    JobStatus,
    Page,
    Project,
    Voice,
)
from ._common import (
    _UNSET,
    AsyncResource,
    DestInput,
    LanguageInput,
    Op,
    ProgressCallback,
    SyncResource,
    _items,
    delete_project_op,
    destination,
    interval_of,
    maybe_project,
    new_idempotency_key,
    poll_op,
    project_list_op,
    project_op,
    rename_op,
    resolve_language,
    seg,
    source_uploads,
    voice_id_of,
)

__all__ = ["Dubbing", "AsyncDubbing"]

SERVICE = "dubbing"
DEFAULT_WAIT_TIMEOUT = 3 * 3600.0
DEFAULT_EXPORT_TIMEOUT = 1800.0
#: How many failed mp4 assemblies ``download`` restarts before giving up.
MAX_EXPORT_RESTARTS = 2

#: ``background_mode`` values: ``duck`` and ``separate``. The former API spelling of
#: ``separate`` is still accepted on input and sent as ``separate``.
BACKGROUND_MODES = {"duck": "duck", "separate": "separate", "demucs": "separate"}

VoiceMap = Mapping[str, Union[int, Voice, Mapping[str, Any]]]


def _background_mode(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    mode = BACKGROUND_MODES.get(str(value).strip().lower())
    if mode is None:
        raise ValueError("background_mode must be 'duck' (lower the original soundtrack "
                         "under speech) or 'separate' (keep music and effects at full level)")
    return mode


def _speakers(value: Optional[int]) -> Optional[int]:
    if value is not None and not 1 <= int(value) <= 10:
        raise ValueError("speakers must be between 1 and 10")
    return int(value) if value is not None else None


def _voice_map(voice_map: Optional[VoiceMap]) -> Optional[Dict[str, Dict[str, int]]]:
    if voice_map is None:
        return None
    result: Dict[str, Dict[str, int]] = {}
    for speaker, voice in voice_map.items():
        if isinstance(voice, Mapping):
            voice_id = voice.get("voice_id")
            if not isinstance(voice_id, int) or isinstance(voice_id, bool):
                raise ValueError(f"voice_map[{speaker!r}] needs an integer voice_id")
        else:
            voice_id = voice_id_of(voice)
        result[str(speaker)] = {"voice_id": int(voice_id or 0)}
    return result


def _dest(path: DestInput, project_id: int, ext: str) -> DestInput:
    return destination(path, f"voices-dub-{int(project_id)}.{ext}")


# --------------------------------------------------------------------------- operations


def _create_op(state: Any, file: Optional[FileContent], youtube_url: Optional[str],
               target_language: Optional[LanguageInput],
               source_language: Optional[LanguageInput], background_mode: str,
               speakers: Optional[int], overlap_pan: Optional[bool],
               auto_emotion: Optional[bool], filename: Optional[str],
               idempotency_key: Optional[str]) -> Op[DubbingDraft]:
    uploads = source_uploads("file", file, youtube_url, filename)
    target_id = yield from resolve_language(state, target_language)
    source_id = yield from resolve_language(state, source_language)
    data = yield Call("POST", f"/services/{SERVICE}/init", form={
        "youtube_url": youtube_url or None,
        "language_id": target_id,
        "source_language_id": source_id,
        "background_mode": _background_mode(background_mode) or "duck",
        "num_speakers": _speakers(speakers),
        "overlap_pan": overlap_pan,
        "auto_emotion": auto_emotion,
    }, uploads=uploads, idempotency_key=new_idempotency_key(idempotency_key))
    return DubbingDraft.from_dict(data if isinstance(data, Mapping) else {})


def _run_body(state: Any, target_language: Optional[LanguageInput],
              source_language: Optional[LanguageInput],
              speakers: Optional[int]) -> Op[Dict[str, Any]]:
    target_id = yield from resolve_language(state, target_language)
    source_id = yield from resolve_language(state, source_language)
    return {"language_id": target_id, "source_language_id": source_id,
            "num_speakers": _speakers(speakers)}


def _preview_op(state: Any, project_id: int, target_language: Optional[LanguageInput],
                source_language: Optional[LanguageInput], speakers: Optional[int],
                idempotency_key: Optional[str]) -> Op[DubbingRun]:
    body = yield from _run_body(state, target_language, source_language, speakers)
    data = yield Call("POST", f"/services/{SERVICE}/preview/{int(project_id)}", json=body,
                      idempotency_key=new_idempotency_key(idempotency_key))
    return DubbingRun.from_dict(data if isinstance(data, Mapping) else {})


def _generate_op(state: Any, project_id: int, target_language: Optional[LanguageInput],
                 source_language: Optional[LanguageInput], speakers: Optional[int],
                 auto_emotion: Optional[bool], voice_map: Optional[VoiceMap],
                 idempotency_key: Optional[str]) -> Op[DubbingRun]:
    body = yield from _run_body(state, target_language, source_language, speakers)
    body["auto_emotion"] = auto_emotion
    body["voice_map"] = _voice_map(voice_map)
    data = yield Call("POST", f"/services/{SERVICE}/generate/{int(project_id)}", json=body,
                      idempotency_key=new_idempotency_key(idempotency_key))
    return DubbingRun.from_dict(data if isinstance(data, Mapping) else {})


def _get_response_op(request_id: str) -> Op[DubbingStatus]:
    data = yield Call("GET", f"/services/{SERVICE}/get-response/{seg(request_id)}")
    return DubbingStatus.from_response(request_id, data if isinstance(data, Mapping) else {})


def _wait_op(request_id: str, interval: float, timeout: Optional[float],
             on_progress: Optional[ProgressCallback]) -> Op[DubbingStatus]:
    result = yield from poll_op(
        lambda: Call("GET", f"/services/{SERVICE}/get-response/{seg(request_id)}"),
        lambda data: DubbingStatus.from_response(
            request_id, data if isinstance(data, Mapping) else {}),
        lambda s: s.status == JobStatus.COMPLETED,
        lambda s: s.status == JobStatus.FAILED,
        interval=interval, timeout=timeout, on_progress=on_progress, what="dubbing run",
        request_id=request_id,
    )
    return result


def _render_op(project_id: int, idempotency_key: Optional[str]) -> Op[DubbingRun]:
    data = yield Call("POST", f"/services/{SERVICE}/render/{int(project_id)}",
                      idempotency_key=new_idempotency_key(idempotency_key))
    return DubbingRun.from_dict(data if isinstance(data, Mapping) else {})


def _regenerate_chunk_op(project_id: int, chunk_id: str,
                         idempotency_key: Optional[str]) -> Op[DubbingRun]:
    data = yield Call("POST",
                      f"/services/{SERVICE}/regenerate-chunk/{int(project_id)}/{seg(chunk_id)}",
                      idempotency_key=new_idempotency_key(idempotency_key))
    return DubbingRun.from_dict(data if isinstance(data, Mapping) else {})


def _export_op(project_id: int) -> Op[DubbingExport]:
    # Not retried automatically: export may charge (dubs made before payment moved to
    # `generate`) and the API does not honour an Idempotency-Key here.
    result = yield Call("POST", f"/services/{SERVICE}/export/{int(project_id)}", full=True)
    data = result.data if isinstance(result.data, Mapping) else {}
    return DubbingExport.from_dict(data, result.status_code)


def _download_op(project_id: int, path: Optional[DestInput], audio_path: Optional[DestInput],
                 interval: float, timeout: Optional[float],
                 on_progress: Optional[ProgressCallback]) -> Op[Any]:
    if path is None and audio_path is None:
        raise ValueError("Pass path=... (the mp4) and/or audio_path=... (the soundtrack).")
    started = yield Now()
    restarts = 0
    while True:
        exported = yield from _export_op(project_id)
        if on_progress is not None:
            on_progress(exported)
        if not exported.pending:
            break
        # The mp4 is being assembled: watch the project until export_status clears.
        while True:
            now = yield Now()
            if timeout is not None and (now - started) + interval > timeout:
                raise TimeoutError(
                    f"The export of project {project_id} was not ready within {timeout:g} "
                    "seconds; it continues on the server.",
                    request_id=exported.request_id, project_id=int(project_id), last=exported,
                )
            yield Sleep(interval)
            project = yield from project_op(SERVICE, project_id)
            status = project.body.get("export_status")
            if status == "pending":
                continue
            if status == "failed":
                restarts += 1
                if restarts > MAX_EXPORT_RESTARTS:
                    raise JobFailedError(
                        f"Assembling the video of project {project_id} failed.",
                        request_id=exported.request_id, project_id=int(project_id),
                        status="failed", result=project,
                    )
            break
    written: Any = None
    if path is not None:
        if not exported.file:
            raise VoicesError(f"Project {project_id} has no video file to download.")
        # An audio-only source is exported as audio: ``file`` is then the mp3.
        ext = "mp3" if exported.audio_only else "mp4"
        written = yield Download(exported.file, _dest(path, project_id, ext))
    if audio_path is not None:
        if not exported.audio:
            raise VoicesError(f"Project {project_id} has no soundtrack to download.")
        audio_written = yield Download(exported.audio, _dest(audio_path, project_id, "mp3"))
        if written is None:
            written = audio_written
    return written


def _settings_op(project_id: int, background_mode: Optional[str], overlap_pan: Optional[bool],
                 auto_emotion: Optional[bool]) -> Op[Optional[Project]]:
    data = yield Call("PUT", f"/services/{SERVICE}/{int(project_id)}/settings", json={
        "background_mode": _background_mode(background_mode),
        "overlap_pan": overlap_pan, "auto_emotion": auto_emotion,
    })
    return maybe_project(data)


def _add_chunk_op(project_id: int, speaker: str, start_ms: int, trans: str,
                  target_duration_ms: Optional[int]) -> Op[Dict[str, Any]]:
    data = yield Call("POST", f"/services/{SERVICE}/{int(project_id)}/chunk", json={
        "speaker": speaker, "start_ms": int(start_ms), "trans": trans,
        "target_duration_ms": target_duration_ms,
    })
    chunk = data.get("chunk") if isinstance(data, Mapping) else None
    return dict(chunk) if isinstance(chunk, Mapping) else {}


def _update_chunk_op(project_id: int, chunk_id: str, fields: Dict[str, Any]) -> Op[Dict[str, Any]]:
    data = yield Call("PUT", f"/services/{SERVICE}/{int(project_id)}/chunk/{seg(chunk_id)}",
                      json=fields, keep_none=True)
    chunk = data.get("chunk") if isinstance(data, Mapping) else None
    return dict(chunk) if isinstance(chunk, Mapping) else {}


def _chunk_fields(trans: Any, speaker: Optional[str], start_ms: Optional[int],
                  target_duration_ms: Optional[int], volume_db: Optional[float],
                  muted: Optional[bool], speed: Optional[float], voice: Any) -> Dict[str, Any]:
    fields: Dict[str, Any] = {}
    if trans is not _UNSET:
        fields["trans"] = trans
    for key, value in (("speaker", speaker), ("start_ms", start_ms),
                       ("target_duration_ms", target_duration_ms), ("volume_db", volume_db),
                       ("muted", muted), ("speed", speed)):
        if value is not None:
            fields[key] = value
    if voice is not _UNSET:
        fields["voice"] = None if voice is None else {"voice_id": voice_id_of(voice)}
    if not fields:
        raise ValueError("Nothing to update: pass at least one field.")
    return fields


def _delete_chunk_op(project_id: int, chunk_id: str) -> Op[Any]:
    data = yield Call("DELETE",
                      f"/services/{SERVICE}/{int(project_id)}/chunk/{seg(chunk_id)}")
    return data


def _formats_op() -> Op[DubbingFormats]:
    data = yield Call("GET", f"/services/{SERVICE}/get-formats")
    return DubbingFormats.from_dict(data if isinstance(data, Mapping) else {})


def _voices_op(state: Any, language: Optional[LanguageInput]) -> Op[List[Voice]]:
    language_id = yield from resolve_language(state, language)
    data = yield Call("GET", f"/services/{SERVICE}/get-voices",
                      params={"language_id": language_id})
    return [Voice.from_dict(x) for x in _items(data, "voices") if isinstance(x, Mapping)]


# --------------------------------------------------------------------------- sync


class Dubbing(SyncResource):
    """``client.dubbing`` - dub a video (file or YouTube link) into another language.

    The flow: :meth:`create` a draft (free) -> optionally :meth:`preview` the first
    seconds -> :meth:`generate` the full dub (**charges the balance**) -> :meth:`wait`
    -> :meth:`download` the clean files. After editing lines, :meth:`render` mixes the
    soundtrack again.
    """

    def create(
        self,
        file: Optional[FileContent] = None,
        *,
        youtube_url: Optional[str] = None,
        target_language: Optional[LanguageInput] = None,
        source_language: Optional[LanguageInput] = None,
        background_mode: str = "duck",
        speakers: Optional[int] = None,
        overlap_pan: Optional[bool] = None,
        auto_emotion: Optional[bool] = None,
        filename: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> DubbingDraft:
        """Create a dubbing project from a video file or a YouTube URL. Free.

        Args:
            file: A path, ``bytes`` or a binary file object (streamed). Exactly one of
                ``file`` and ``youtube_url``. Formats: ``client.dubbing.formats()``.
            youtube_url: A YouTube watch URL.
            target_language: Language to dub into (id or code). Required by
                :meth:`generate` at the latest.
            source_language: Language spoken in the video; detected when omitted.
            background_mode: ``"duck"`` lowers the original soundtrack while a line
                plays; ``"separate"`` keeps music and effects at full level.
            speakers: Number of speakers (1-10); detected when omitted.
            overlap_pan: Pan overlapping speakers apart in stereo (default on).
            auto_emotion: Voice every line with an automatically picked emotion. Adds a
                per-minute surcharge (``client.services.get("dubbing").prices``), charged
                with :meth:`generate`.

        Returns:
            A :class:`~voices_az.types.DubbingDraft` with ``project_id`` and the quote.
        """
        return self._run(_create_op(self._client._state, file, youtube_url, target_language,
                                    source_language, background_mode, speakers, overlap_pan,
                                    auto_emotion, filename, idempotency_key))

    def preview(
        self,
        project_id: int,
        *,
        target_language: Optional[LanguageInput] = None,
        source_language: Optional[LanguageInput] = None,
        speakers: Optional[int] = None,
        idempotency_key: Optional[str] = None,
    ) -> DubbingRun:
        """Dub the first seconds so the result can be judged before paying.

        A few previews per project are free; beyond that each one **is charged**
        (``price`` on the result). Only while the project is a draft. Wait for it with
        :meth:`wait`; the result's ``preview_audio_url`` / ``audio_url`` is the preview.
        """
        return self._run(_preview_op(self._client._state, project_id, target_language,
                                     source_language, speakers, idempotency_key))

    def generate(
        self,
        project_id: int,
        *,
        target_language: Optional[LanguageInput] = None,
        source_language: Optional[LanguageInput] = None,
        speakers: Optional[int] = None,
        auto_emotion: Optional[bool] = None,
        voice_map: Optional[VoiceMap] = None,
        idempotency_key: Optional[str] = None,
    ) -> DubbingRun:
        """Dub the whole video. **Charges the balance** (the dubbing tariff x minutes,
        plus the auto-emotion surcharge when it is on).

        Args:
            voice_map: Voice per detected speaker, e.g. ``{"SPEAKER_00": 41}``. Speaker
                keys are in ``client.dubbing.get_project(id).body["speakers"]``. Omit it
                to give every speaker a default voice of matching gender.

        Wait for the run with ``client.dubbing.wait(run.request_id)``. From this call on
        :meth:`export` / :meth:`download` are free.
        """
        return self._run(_generate_op(self._client._state, project_id, target_language,
                                      source_language, speakers, auto_emotion, voice_map,
                                      idempotency_key))

    def get_response(self, request_id: str) -> DubbingStatus:
        """Stage and percentage of a run (preview, dub, render, re-recorded line, or an
        mp4 assembly)."""
        return self._run(_get_response_op(request_id))

    def wait(
        self,
        request_id: str,
        *,
        poll_interval: Optional[float] = None,
        wait_timeout: Optional[float] = DEFAULT_WAIT_TIMEOUT,
        on_progress: Optional[ProgressCallback] = None,
    ) -> DubbingStatus:
        """Poll a run until it is ``COMPLETED``.

        Raises :class:`~voices_az.JobFailedError` when it fails and
        :class:`voices_az.TimeoutError` after ``wait_timeout`` seconds.
        """
        return self._run(_wait_op(request_id, interval_of(poll_interval, self._poll_interval),
                                  wait_timeout, on_progress))

    def render(self, project_id: int, *, idempotency_key: Optional[str] = None) -> DubbingRun:
        """Mix the soundtrack again after edits. A few renders are free; beyond that each
        one **is charged** (``price`` on the result)."""
        return self._run(_render_op(project_id, idempotency_key))

    def regenerate_chunk(self, project_id: int, chunk_id: str, *,
                         idempotency_key: Optional[str] = None) -> DubbingRun:
        """Re-record one line. **Charged** (``price`` on the result)."""
        return self._run(_regenerate_chunk_op(project_id, chunk_id, idempotency_key))

    def export(self, project_id: int) -> DubbingExport:
        """Ask for the clean (watermark-free) files - one call, no waiting.

        Returns ``pending=True`` while the mp4 is being assembled (call again later, or
        use :meth:`download`, which does the waiting). Free for dubs paid on
        :meth:`generate`; a project dubbed before that rule **is charged once** here.
        Never retried automatically.
        """
        return self._run(_export_op(project_id))

    def download(
        self,
        project_id: int,
        path: Optional[DestInput] = None,
        *,
        audio_path: Optional[DestInput] = None,
        poll_interval: Optional[float] = None,
        wait_timeout: Optional[float] = DEFAULT_EXPORT_TIMEOUT,
        on_progress: Optional[ProgressCallback] = None,
    ) -> Any:
        """Export the clean files, waiting for the mp4 assembly if needed, and save them.

        A project made from an audio file (mp3, wav) has no video: its export is the dubbed
        mp3, saved to ``path`` (``.mp3`` when a directory is given).

        Args:
            path: Where to save the mp4 (a file path, an existing directory, or a binary
                file object).
            audio_path: Where to save the soundtrack alone (mp3), optional.

        Returns:
            The :class:`~pathlib.Path` of the mp4 (or of the mp3 when only
            ``audio_path`` is given); bytes written for file objects.

        See :meth:`export` about charging.
        """
        return self._run(_download_op(project_id, path, audio_path,
                                      interval_of(poll_interval, self._poll_interval),
                                      wait_timeout, on_progress))

    def update_settings(self, project_id: int, *, background_mode: Optional[str] = None,
                        overlap_pan: Optional[bool] = None,
                        auto_emotion: Optional[bool] = None) -> Optional[Project]:
        """Change mix settings. ``background_mode``/``overlap_pan`` apply at mix time;
        ``auto_emotion`` re-records the affected lines on the next :meth:`render`."""
        return self._run(_settings_op(project_id, background_mode, overlap_pan, auto_emotion))

    def add_chunk(self, project_id: int, *, speaker: str, start_ms: int, trans: str,
                  target_duration_ms: Optional[int] = None) -> Dict[str, Any]:
        """Add a spoken line (``trans`` is the text to voice). Returns the new line."""
        return self._run(_add_chunk_op(project_id, speaker, start_ms, trans,
                                       target_duration_ms))

    def update_chunk(
        self,
        project_id: int,
        chunk_id: str,
        *,
        trans: Any = _UNSET,
        speaker: Optional[str] = None,
        start_ms: Optional[int] = None,
        target_duration_ms: Optional[int] = None,
        volume_db: Optional[float] = None,
        muted: Optional[bool] = None,
        speed: Optional[float] = None,
        voice: Any = _UNSET,
    ) -> Dict[str, Any]:
        """Edit a line. Only the fields you pass are sent.

        ``voice`` takes a voice id (or :class:`~voices_az.types.Voice`) for this line, or
        ``None`` to return the line to its speaker's voice. Changing ``trans``, ``speed``
        or the voice marks the line for re-recording on the next :meth:`render`.
        """
        return self._run(_update_chunk_op(project_id, chunk_id, _chunk_fields(
            trans, speaker, start_ms, target_duration_ms, volume_db, muted, speed, voice)))

    def delete_chunk(self, project_id: int, chunk_id: str) -> Any:
        """Delete a line."""
        return self._run(_delete_chunk_op(project_id, chunk_id))

    def formats(self) -> DubbingFormats:
        """Accepted source formats and background modes."""
        return self._run(_formats_op())

    def voices(self, *, language: Optional[LanguageInput] = None) -> List[Voice]:
        """Voices available for dubbing, optionally for one language."""
        return self._run(_voices_op(self._client._state, language))

    def list_projects(self, *, page: int = 1, title: Optional[str] = None,
                      status: Optional[int] = None,
                      language: Optional[LanguageInput] = None) -> Page[Project]:
        """The account's dubbing projects, 20 per page."""
        return self._run(project_list_op(SERVICE, page, title, status, language,
                                         self._client._state))

    def get_project(self, project_id: int) -> Project:
        """One project: ``body`` has ``speakers``, ``chunks`` (the per-line timeline),
        ``audio_url`` (watermarked preview of the soundtrack) and ``export_status``."""
        return self._run(project_op(SERVICE, project_id))

    def delete_project(self, project_id: int) -> None:
        """Delete a project."""
        return self._run(delete_project_op(SERVICE, project_id))

    def rename(self, project_id: int, title: str) -> Optional[Project]:
        """Rename a project (3-255 characters)."""
        return self._run(rename_op(SERVICE, project_id, title))


# --------------------------------------------------------------------------- async


class AsyncDubbing(AsyncResource):
    """Async version of :class:`Dubbing`. ``generate`` charges the balance."""

    async def create(
        self,
        file: Optional[FileContent] = None,
        *,
        youtube_url: Optional[str] = None,
        target_language: Optional[LanguageInput] = None,
        source_language: Optional[LanguageInput] = None,
        background_mode: str = "duck",
        speakers: Optional[int] = None,
        overlap_pan: Optional[bool] = None,
        auto_emotion: Optional[bool] = None,
        filename: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> DubbingDraft:
        """See :meth:`Dubbing.create`."""
        return await self._run(_create_op(self._client._state, file, youtube_url,
                                          target_language, source_language, background_mode,
                                          speakers, overlap_pan, auto_emotion, filename,
                                          idempotency_key))

    async def preview(
        self,
        project_id: int,
        *,
        target_language: Optional[LanguageInput] = None,
        source_language: Optional[LanguageInput] = None,
        speakers: Optional[int] = None,
        idempotency_key: Optional[str] = None,
    ) -> DubbingRun:
        """See :meth:`Dubbing.preview`."""
        return await self._run(_preview_op(self._client._state, project_id, target_language,
                                           source_language, speakers, idempotency_key))

    async def generate(
        self,
        project_id: int,
        *,
        target_language: Optional[LanguageInput] = None,
        source_language: Optional[LanguageInput] = None,
        speakers: Optional[int] = None,
        auto_emotion: Optional[bool] = None,
        voice_map: Optional[VoiceMap] = None,
        idempotency_key: Optional[str] = None,
    ) -> DubbingRun:
        """**Charges the balance.** See :meth:`Dubbing.generate`."""
        return await self._run(_generate_op(self._client._state, project_id, target_language,
                                            source_language, speakers, auto_emotion,
                                            voice_map, idempotency_key))

    async def get_response(self, request_id: str) -> DubbingStatus:
        """See :meth:`Dubbing.get_response`."""
        return await self._run(_get_response_op(request_id))

    async def wait(
        self,
        request_id: str,
        *,
        poll_interval: Optional[float] = None,
        wait_timeout: Optional[float] = DEFAULT_WAIT_TIMEOUT,
        on_progress: Optional[ProgressCallback] = None,
    ) -> DubbingStatus:
        """See :meth:`Dubbing.wait`."""
        return await self._run(_wait_op(request_id,
                                        interval_of(poll_interval, self._poll_interval),
                                        wait_timeout, on_progress))

    async def render(self, project_id: int, *,
                     idempotency_key: Optional[str] = None) -> DubbingRun:
        """See :meth:`Dubbing.render`."""
        return await self._run(_render_op(project_id, idempotency_key))

    async def regenerate_chunk(self, project_id: int, chunk_id: str, *,
                               idempotency_key: Optional[str] = None) -> DubbingRun:
        """See :meth:`Dubbing.regenerate_chunk`."""
        return await self._run(_regenerate_chunk_op(project_id, chunk_id, idempotency_key))

    async def export(self, project_id: int) -> DubbingExport:
        """See :meth:`Dubbing.export`."""
        return await self._run(_export_op(project_id))

    async def download(
        self,
        project_id: int,
        path: Optional[DestInput] = None,
        *,
        audio_path: Optional[DestInput] = None,
        poll_interval: Optional[float] = None,
        wait_timeout: Optional[float] = DEFAULT_EXPORT_TIMEOUT,
        on_progress: Optional[ProgressCallback] = None,
    ) -> Any:
        """See :meth:`Dubbing.download`."""
        return await self._run(_download_op(project_id, path, audio_path,
                                            interval_of(poll_interval, self._poll_interval),
                                            wait_timeout, on_progress))

    async def update_settings(self, project_id: int, *, background_mode: Optional[str] = None,
                              overlap_pan: Optional[bool] = None,
                              auto_emotion: Optional[bool] = None) -> Optional[Project]:
        """See :meth:`Dubbing.update_settings`."""
        return await self._run(_settings_op(project_id, background_mode, overlap_pan,
                                            auto_emotion))

    async def add_chunk(self, project_id: int, *, speaker: str, start_ms: int, trans: str,
                        target_duration_ms: Optional[int] = None) -> Dict[str, Any]:
        """See :meth:`Dubbing.add_chunk`."""
        return await self._run(_add_chunk_op(project_id, speaker, start_ms, trans,
                                             target_duration_ms))

    async def update_chunk(
        self,
        project_id: int,
        chunk_id: str,
        *,
        trans: Any = _UNSET,
        speaker: Optional[str] = None,
        start_ms: Optional[int] = None,
        target_duration_ms: Optional[int] = None,
        volume_db: Optional[float] = None,
        muted: Optional[bool] = None,
        speed: Optional[float] = None,
        voice: Any = _UNSET,
    ) -> Dict[str, Any]:
        """See :meth:`Dubbing.update_chunk`."""
        return await self._run(_update_chunk_op(project_id, chunk_id, _chunk_fields(
            trans, speaker, start_ms, target_duration_ms, volume_db, muted, speed, voice)))

    async def delete_chunk(self, project_id: int, chunk_id: str) -> Any:
        """See :meth:`Dubbing.delete_chunk`."""
        return await self._run(_delete_chunk_op(project_id, chunk_id))

    async def formats(self) -> DubbingFormats:
        """See :meth:`Dubbing.formats`."""
        return await self._run(_formats_op())

    async def voices(self, *, language: Optional[LanguageInput] = None) -> List[Voice]:
        """See :meth:`Dubbing.voices`."""
        return await self._run(_voices_op(self._client._state, language))

    async def list_projects(self, *, page: int = 1, title: Optional[str] = None,
                            status: Optional[int] = None,
                            language: Optional[LanguageInput] = None) -> Page[Project]:
        """See :meth:`Dubbing.list_projects`."""
        return await self._run(project_list_op(SERVICE, page, title, status, language,
                                               self._client._state))

    async def get_project(self, project_id: int) -> Project:
        """See :meth:`Dubbing.get_project`."""
        return await self._run(project_op(SERVICE, project_id))

    async def delete_project(self, project_id: int) -> None:
        """See :meth:`Dubbing.delete_project`."""
        return await self._run(delete_project_op(SERVICE, project_id))

    async def rename(self, project_id: int, title: str) -> Optional[Project]:
        """See :meth:`Dubbing.rename`."""
        return await self._run(rename_op(SERVICE, project_id, title))
