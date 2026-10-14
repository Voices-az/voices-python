"""Speech-to-text: ``client.stt``."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Literal, Mapping, Optional, Union, overload

from .._base import Call, Download, FileContent
from ..types import (
    ExportedFile,
    Page,
    Project,
    ProjectStatusCode,
    Recognition,
    STTUpload,
    Transcript,
)
from ._common import (
    AsyncResource,
    DestInput,
    LanguageInput,
    Op,
    ProgressCallback,
    SyncResource,
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
    source_uploads,
)

__all__ = ["STT", "AsyncSTT"]

SERVICE = "speech-to-text"
DEFAULT_WAIT_TIMEOUT = 3600.0
EXPORT_FORMATS = ("txt", "srt", "vtt", "sbv", "dfxp", "csv")
_DONE = (ProjectStatusCode.COMPLETED, ProjectStatusCode.ORDERED)


def _run_options(language_id: Optional[int], speakers: Optional[int],
                 remove_background: Optional[bool],
                 convert_numbers: Optional[bool]) -> Dict[str, Any]:
    if speakers is not None and not 1 <= int(speakers) <= 10:
        raise ValueError("speakers must be between 1 and 10")
    return {
        "language_id": language_id,
        "diarize": int(speakers) if speakers is not None else None,
        # Wire name of "strip music and background noise first".
        "demucs": remove_background,
        "convert_numbers": convert_numbers,
    }


def _transcript_op(project_id: int) -> Op[Transcript]:
    project = yield from project_op(SERVICE, project_id)
    return Transcript.from_project(project)


def _wait_op(project_id: int, interval: float, timeout: Optional[float],
             on_progress: Optional[ProgressCallback], delay_first: bool = False,
             request_id: Optional[str] = None) -> Op[Transcript]:
    result = yield from poll_op(
        lambda: Call("GET", f"/services/{SERVICE}/{int(project_id)}"),
        lambda data: Transcript.from_project(project_from(data)),
        lambda t: t.status.id in _DONE,
        lambda t: t.status.id == ProjectStatusCode.REJECTED,
        interval=interval, timeout=timeout, on_progress=on_progress, what="recognition",
        request_id=request_id, project_id=int(project_id), delay_first=delay_first,
    )
    return result


def _recognize_op(state: Any, file: Optional[FileContent], youtube_url: Optional[str],
                  language: LanguageInput, speakers: Optional[int],
                  remove_background: Optional[bool], convert_numbers: Optional[bool],
                  filename: Optional[str], wait: bool, interval: float,
                  timeout: Optional[float], on_progress: Optional[ProgressCallback],
                  idempotency_key: Optional[str]) -> Op[Union[Transcript, Recognition]]:
    if language is None:
        raise ValueError("language is required: the language spoken in the source")
    uploads = source_uploads("voice", file, youtube_url, filename)
    language_id = yield from resolve_language(state, language)
    form = _run_options(language_id, speakers, remove_background, convert_numbers)
    form["youtube_url"] = youtube_url or None
    data = yield Call("POST", f"/services/{SERVICE}/recognize", form=form, uploads=uploads,
                      idempotency_key=new_idempotency_key(idempotency_key))
    started = Recognition.from_dict(data if isinstance(data, Mapping) else {})
    if not wait:
        return started
    result = yield from _wait_op(started.project_id, interval, timeout, on_progress,
                                 delay_first=True, request_id=started.request_id)
    return result


def _upload_op(file: Optional[FileContent], youtube_url: Optional[str],
               project_id: Optional[int], filename: Optional[str],
               idempotency_key: Optional[str]) -> Op[STTUpload]:
    uploads = source_uploads("voice", file, youtube_url, filename)
    data = yield Call("POST", f"/services/{SERVICE}/init",
                      form={"youtube_url": youtube_url or None, "project_id": project_id},
                      uploads=uploads, idempotency_key=new_idempotency_key(idempotency_key))
    return STTUpload.from_dict(data if isinstance(data, Mapping) else {})


def _generate_op(state: Any, project_id: int, language: LanguageInput,
                 speakers: Optional[int], remove_background: Optional[bool],
                 convert_numbers: Optional[bool], idempotency_key: Optional[str]) -> Op[str]:
    if language is None:
        raise ValueError("language is required: the language spoken in the source")
    language_id = yield from resolve_language(state, language)
    data = yield Call("POST", f"/services/{SERVICE}/generate/{int(project_id)}",
                      json=_run_options(language_id, speakers, remove_background,
                                        convert_numbers),
                      idempotency_key=new_idempotency_key(idempotency_key))
    return str(data.get("request_id") or "") if isinstance(data, Mapping) else ""


def _update_block_op(project_id: int, block_id: Union[int, str], text: str) -> Op[Optional[str]]:
    data = yield Call("PUT", f"/services/{SERVICE}/{int(project_id)}/{seg(block_id)}",
                      json={"text": text})
    return data.get("text") if isinstance(data, Mapping) else None


def _formats_op() -> Op[Dict[str, str]]:
    data = yield Call("GET", f"/services/{SERVICE}/get-formats")
    formats = data.get("formats") if isinstance(data, Mapping) else None
    return {str(k): str(v) for k, v in formats.items()} if isinstance(formats, Mapping) else {}


def _export_op(project_id: int, format: str) -> Op[ExportedFile]:
    data = yield Call("POST", f"/services/{SERVICE}/export/{int(project_id)}",
                      json={"format": format})
    return ExportedFile.from_dict(data if isinstance(data, Mapping) else {})


def _download_op(project_id: int, path: DestInput, format: str) -> Op[Union[Path, int]]:
    exported = yield from _export_op(project_id, format)
    if not exported.file:
        from ..exceptions import VoicesError

        raise VoicesError(f"Project {project_id} has no transcript file to download.")
    written: Union[Path, int] = yield Download(
        exported.file, destination(path, f"voices-stt-{int(project_id)}.{format}"))
    return written


# --------------------------------------------------------------------------- sync


class STT(SyncResource):
    """``client.stt`` - speech-to-text.

    **The balance is charged when recognition starts** (:meth:`recognize`, or
    :meth:`generate` after :meth:`upload`), at the per-minute tariff of
    ``client.services.get("speech-to-text")``. Exporting the transcript afterwards is free.
    """

    @overload
    def recognize(
        self,
        file: Optional[FileContent] = None,
        *,
        youtube_url: Optional[str] = None,
        language: LanguageInput,
        speakers: Optional[int] = None,
        remove_background: Optional[bool] = None,
        convert_numbers: Optional[bool] = None,
        filename: Optional[str] = None,
        wait: Literal[True] = ...,
        poll_interval: Optional[float] = None,
        wait_timeout: Optional[float] = DEFAULT_WAIT_TIMEOUT,
        on_progress: Optional[ProgressCallback] = None,
        idempotency_key: Optional[str] = None,
    ) -> Transcript: ...

    @overload
    def recognize(
        self,
        file: Optional[FileContent] = None,
        *,
        youtube_url: Optional[str] = None,
        language: LanguageInput,
        speakers: Optional[int] = None,
        remove_background: Optional[bool] = None,
        convert_numbers: Optional[bool] = None,
        filename: Optional[str] = None,
        wait: Literal[False],
        poll_interval: Optional[float] = None,
        wait_timeout: Optional[float] = DEFAULT_WAIT_TIMEOUT,
        on_progress: Optional[ProgressCallback] = None,
        idempotency_key: Optional[str] = None,
    ) -> Recognition: ...

    def recognize(
        self,
        file: Optional[FileContent] = None,
        *,
        youtube_url: Optional[str] = None,
        language: LanguageInput,
        speakers: Optional[int] = None,
        remove_background: Optional[bool] = None,
        convert_numbers: Optional[bool] = None,
        filename: Optional[str] = None,
        wait: bool = True,
        poll_interval: Optional[float] = None,
        wait_timeout: Optional[float] = DEFAULT_WAIT_TIMEOUT,
        on_progress: Optional[ProgressCallback] = None,
        idempotency_key: Optional[str] = None,
    ) -> Union[Transcript, Recognition]:
        """Transcribe an audio/video file or a YouTube video. **Charges the balance.**

        Uploads the source (streamed from disk, never loaded whole into memory), charges
        the account, queues recognition and - by default - waits for the transcript.

        Args:
            file: A path, ``bytes`` or a binary file object. Exactly one of ``file`` and
                ``youtube_url``.
            youtube_url: A YouTube watch URL.
            language: The language spoken in the source (id or code, e.g. ``"az"``).
            speakers: Number of speakers to separate (1-10; ``1`` = no separation).
            remove_background: Strip music and background noise first (slower, better on
                noisy sources).
            convert_numbers: Write numbers as digits instead of words.
            filename: Name to send for ``file`` when it is bytes or a nameless stream.
            wait: ``False`` returns a :class:`~voices_az.types.Recognition` right after
                queueing; call :meth:`wait` with its ``project_id`` later.
            poll_interval: Seconds between polls (at least 2).
            wait_timeout: Give up waiting after this many seconds; ``None`` waits
                indefinitely.
            on_progress: Called with every polled :class:`~voices_az.types.Transcript`.
            idempotency_key: Sent as ``Idempotency-Key`` (generated when omitted), so a
                retried upload is never charged twice.

        Returns:
            A :class:`~voices_az.types.Transcript` (``.text``, ``.segments``) when
            ``wait`` is true, otherwise a :class:`~voices_az.types.Recognition`.

        Raises:
            InsufficientBalanceError: The balance does not cover the run.
            PayloadTooLargeError: The file is over the upload limit.
            JobFailedError: Recognition was rejected.
            TimeoutError: ``wait_timeout`` elapsed (the run continues on the server).
        """
        return self._run(_recognize_op(
            self._client._state, file, youtube_url, language, speakers, remove_background,
            convert_numbers, filename, wait, interval_of(poll_interval, self._poll_interval),
            wait_timeout, on_progress, idempotency_key,
        ))

    def upload(
        self,
        file: Optional[FileContent] = None,
        *,
        youtube_url: Optional[str] = None,
        project_id: Optional[int] = None,
        filename: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> STTUpload:
        """Upload a source without starting recognition (``POST .../init``).

        Returns the detected duration and the quote (``price``); start the run with
        :meth:`generate`. Pass ``project_id`` to replace the source of an existing draft.
        Nothing is charged here.
        """
        return self._run(_upload_op(file, youtube_url, project_id, filename, idempotency_key))

    def generate(
        self,
        project_id: int,
        *,
        language: LanguageInput,
        speakers: Optional[int] = None,
        remove_background: Optional[bool] = None,
        convert_numbers: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
    ) -> str:
        """Start recognition on an uploaded source. **Charges the balance.**

        Returns the run's ``request_id``; wait for the transcript with
        ``client.stt.wait(project_id)``.
        """
        return self._run(_generate_op(
            self._client._state, project_id, language, speakers, remove_background,
            convert_numbers, idempotency_key,
        ))

    def wait(
        self,
        project_id: int,
        *,
        poll_interval: Optional[float] = None,
        wait_timeout: Optional[float] = DEFAULT_WAIT_TIMEOUT,
        on_progress: Optional[ProgressCallback] = None,
    ) -> Transcript:
        """Poll a project until recognition is done; returns the transcript.

        Raises :class:`~voices_az.JobFailedError` when the project is rejected and
        :class:`voices_az.TimeoutError` after ``wait_timeout`` seconds.
        """
        return self._run(_wait_op(project_id, interval_of(poll_interval, self._poll_interval),
                                  wait_timeout, on_progress))

    def get_transcript(self, project_id: int) -> Transcript:
        """The project's transcript as it is now (no waiting)."""
        return self._run(_transcript_op(project_id))

    def update_block(self, project_id: int, block_id: Union[int, str], text: str) -> Optional[str]:
        """Correct the text of one recognised block. Returns the stored text."""
        return self._run(_update_block_op(project_id, block_id, text))

    def formats(self) -> Dict[str, str]:
        """Transcript export formats, ``{"srt": "SRT", ...}``."""
        return self._run(_formats_op())

    def export(self, project_id: int, *, format: str = "txt") -> ExportedFile:
        """Render the transcript as ``txt``, ``srt``, ``vtt``, ``sbv``, ``dfxp`` or ``csv``
        and return its url. Free: recognition was paid for when it started."""
        return self._run(_export_op(project_id, format))

    def download(self, project_id: int, path: DestInput, *, format: str = "txt"
                 ) -> Union[Path, int]:
        """Export the transcript in ``format`` and save it to ``path`` (a file path, an
        existing directory, or a binary file object)."""
        return self._run(_download_op(project_id, path, format))

    def list_projects(self, *, page: int = 1, title: Optional[str] = None,
                      status: Optional[int] = None,
                      language: Optional[LanguageInput] = None) -> Page[Project]:
        """The account's speech-to-text projects, 20 per page."""
        return self._run(project_list_op(SERVICE, page, title, status, language,
                                         self._client._state))

    def get_project(self, project_id: int) -> Project:
        """One project; recognised blocks are in ``body["blocks"]``."""
        return self._run(project_op(SERVICE, project_id))

    def delete_project(self, project_id: int) -> None:
        """Delete a project."""
        return self._run(delete_project_op(SERVICE, project_id))

    def rename(self, project_id: int, title: str) -> Optional[Project]:
        """Rename a project (3-255 characters)."""
        return self._run(rename_op(SERVICE, project_id, title))


# --------------------------------------------------------------------------- async


class AsyncSTT(AsyncResource):
    """Async version of :class:`STT`. The balance is charged when recognition starts."""

    @overload
    async def recognize(
        self,
        file: Optional[FileContent] = None,
        *,
        youtube_url: Optional[str] = None,
        language: LanguageInput,
        speakers: Optional[int] = None,
        remove_background: Optional[bool] = None,
        convert_numbers: Optional[bool] = None,
        filename: Optional[str] = None,
        wait: Literal[True] = ...,
        poll_interval: Optional[float] = None,
        wait_timeout: Optional[float] = DEFAULT_WAIT_TIMEOUT,
        on_progress: Optional[ProgressCallback] = None,
        idempotency_key: Optional[str] = None,
    ) -> Transcript: ...

    @overload
    async def recognize(
        self,
        file: Optional[FileContent] = None,
        *,
        youtube_url: Optional[str] = None,
        language: LanguageInput,
        speakers: Optional[int] = None,
        remove_background: Optional[bool] = None,
        convert_numbers: Optional[bool] = None,
        filename: Optional[str] = None,
        wait: Literal[False],
        poll_interval: Optional[float] = None,
        wait_timeout: Optional[float] = DEFAULT_WAIT_TIMEOUT,
        on_progress: Optional[ProgressCallback] = None,
        idempotency_key: Optional[str] = None,
    ) -> Recognition: ...

    async def recognize(
        self,
        file: Optional[FileContent] = None,
        *,
        youtube_url: Optional[str] = None,
        language: LanguageInput,
        speakers: Optional[int] = None,
        remove_background: Optional[bool] = None,
        convert_numbers: Optional[bool] = None,
        filename: Optional[str] = None,
        wait: bool = True,
        poll_interval: Optional[float] = None,
        wait_timeout: Optional[float] = DEFAULT_WAIT_TIMEOUT,
        on_progress: Optional[ProgressCallback] = None,
        idempotency_key: Optional[str] = None,
    ) -> Union[Transcript, Recognition]:
        """**Charges the balance.** See :meth:`STT.recognize`."""
        return await self._run(_recognize_op(
            self._client._state, file, youtube_url, language, speakers, remove_background,
            convert_numbers, filename, wait, interval_of(poll_interval, self._poll_interval),
            wait_timeout, on_progress, idempotency_key,
        ))

    async def upload(
        self,
        file: Optional[FileContent] = None,
        *,
        youtube_url: Optional[str] = None,
        project_id: Optional[int] = None,
        filename: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> STTUpload:
        """See :meth:`STT.upload`."""
        return await self._run(_upload_op(file, youtube_url, project_id, filename,
                                          idempotency_key))

    async def generate(
        self,
        project_id: int,
        *,
        language: LanguageInput,
        speakers: Optional[int] = None,
        remove_background: Optional[bool] = None,
        convert_numbers: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
    ) -> str:
        """**Charges the balance.** See :meth:`STT.generate`."""
        return await self._run(_generate_op(
            self._client._state, project_id, language, speakers, remove_background,
            convert_numbers, idempotency_key,
        ))

    async def wait(
        self,
        project_id: int,
        *,
        poll_interval: Optional[float] = None,
        wait_timeout: Optional[float] = DEFAULT_WAIT_TIMEOUT,
        on_progress: Optional[ProgressCallback] = None,
    ) -> Transcript:
        """See :meth:`STT.wait`."""
        return await self._run(_wait_op(project_id,
                                        interval_of(poll_interval, self._poll_interval),
                                        wait_timeout, on_progress))

    async def get_transcript(self, project_id: int) -> Transcript:
        """See :meth:`STT.get_transcript`."""
        return await self._run(_transcript_op(project_id))

    async def update_block(self, project_id: int, block_id: Union[int, str],
                           text: str) -> Optional[str]:
        """See :meth:`STT.update_block`."""
        return await self._run(_update_block_op(project_id, block_id, text))

    async def formats(self) -> Dict[str, str]:
        """See :meth:`STT.formats`."""
        return await self._run(_formats_op())

    async def export(self, project_id: int, *, format: str = "txt") -> ExportedFile:
        """See :meth:`STT.export`."""
        return await self._run(_export_op(project_id, format))

    async def download(self, project_id: int, path: DestInput, *, format: str = "txt"
                       ) -> Union[Path, int]:
        """See :meth:`STT.download`."""
        return await self._run(_download_op(project_id, path, format))

    async def list_projects(self, *, page: int = 1, title: Optional[str] = None,
                            status: Optional[int] = None,
                            language: Optional[LanguageInput] = None) -> Page[Project]:
        """See :meth:`STT.list_projects`."""
        return await self._run(project_list_op(SERVICE, page, title, status, language,
                                               self._client._state))

    async def get_project(self, project_id: int) -> Project:
        """See :meth:`STT.get_project`."""
        return await self._run(project_op(SERVICE, project_id))

    async def delete_project(self, project_id: int) -> None:
        """See :meth:`STT.delete_project`."""
        return await self._run(delete_project_op(SERVICE, project_id))

    async def rename(self, project_id: int, title: str) -> Optional[Project]:
        """See :meth:`STT.rename`."""
        return await self._run(rename_op(SERVICE, project_id, title))
