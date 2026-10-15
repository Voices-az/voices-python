"""Typed objects returned by the client.

Every object keeps the decoded JSON it was built from in ``raw`` (excluded from
``repr``), so a field the API adds later is never out of reach. Field names follow the
API's own names. Money amounts are :class:`decimal.Decimal`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import IntEnum
from typing import Any, Dict, Generic, List, Mapping, Optional, TypeVar

__all__ = [
    "JobStatus",
    "ProjectStatusCode",
    "Gender",
    "Language",
    "Price",
    "Balance",
    "Transaction",
    "Page",
    "Voice",
    "Service",
    "ProjectStatus",
    "Project",
    "TTSBlock",
    "SynthesisBlock",
    "Synthesis",
    "ExportedFile",
    "STTUpload",
    "Recognition",
    "Segment",
    "Transcript",
    "DubbingDraft",
    "DubbingRun",
    "DubbingStatus",
    "DubbingExport",
    "DubbingFormats",
]

T = TypeVar("T")


class JobStatus:
    """Status strings of a queued run (``get-response``)."""

    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ProjectStatusCode(IntEnum):
    """``status.id`` of a project."""

    DRAFT = 1
    IN_PROGRESS = 2
    COMPLETED = 3
    ORDERED = 4
    REJECTED = 5
    WAITING_FOR_ORDERING = 6


def _dec(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _int(value: Any) -> Optional[int]:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> Optional[float]:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _map(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, Mapping):
        return list(value.values())
    return []


@dataclass
class Gender:
    id: Optional[int]
    title: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: Any) -> Optional[Gender]:
        if not isinstance(data, Mapping):
            return None
        return cls(id=_int(data.get("id")), title=data.get("title"), raw=dict(data))


@dataclass
class Language:
    """A language from ``GET /languages``. ``id`` is what ``language_id`` expects."""

    id: int
    code: Optional[str]
    title: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Language:
        return cls(id=int(data.get("id") or 0), code=data.get("code"), title=data.get("title"),
                   raw=dict(data))

    @classmethod
    def maybe(cls, data: Any) -> Optional[Language]:
        return cls.from_dict(data) if isinstance(data, Mapping) else None


@dataclass
class Price:
    amount: Decimal
    currency: str
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def maybe(cls, data: Any) -> Optional[Price]:
        if not isinstance(data, Mapping):
            return None
        amount = _dec(data.get("amount"))
        if amount is None:
            return None
        return cls(amount=amount, currency=str(data.get("currency") or "AZN"), raw=dict(data))


@dataclass
class Balance:
    amount: Decimal
    currency: str
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Balance:
        inner = data.get("balance", data)
        inner = inner if isinstance(inner, Mapping) else {"amount": inner}
        return cls(amount=_dec(inner.get("amount")) or Decimal("0"),
                   currency=str(inner.get("currency") or "AZN"), raw=dict(data))


@dataclass
class Transaction:
    id: Optional[int]
    amount: Optional[Decimal]
    currency: Optional[str]
    balance_snapshot: Optional[Decimal]
    description: Optional[str]
    operation_type: Optional[str]
    balance_type: Optional[str]
    status: Optional[str]
    created_at: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Transaction:
        return cls(
            id=_int(data.get("id")),
            amount=_dec(data.get("amount")),
            currency=data.get("currency"),
            balance_snapshot=_dec(data.get("balance_snapshot")),
            description=data.get("description"),
            operation_type=data.get("operation_type"),
            balance_type=data.get("balance_type"),
            status=data.get("status"),
            created_at=data.get("created_at"),
            raw=dict(data),
        )


@dataclass
class Page(Generic[T]):
    """One page of a paginated list."""

    items: List[T]
    current_page: Optional[int] = None
    last_page: Optional[int] = None
    per_page: Optional[int] = None
    total: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    @property
    def has_more(self) -> bool:
        if self.current_page is None or self.last_page is None:
            return False
        return self.current_page < self.last_page


@dataclass
class Voice:
    """A voice from ``GET /get-voices`` or ``GET /services/dubbing/get-voices``."""

    id: int
    full_name: Optional[str]
    gender: Optional[Gender]
    languages: List[Language]
    age: Optional[int] = None
    is_public: Optional[bool] = None
    is_rent: Optional[bool] = None
    price: Any = None
    created_at: Optional[str] = None
    image: Optional[str] = None
    source: Optional[str] = None
    favorite: Optional[bool] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Voice:
        return cls(
            id=int(data.get("id") or 0),
            full_name=data.get("full_name"),
            gender=Gender.from_dict(data.get("gender")),
            languages=[Language.from_dict(x) for x in _list(data.get("languages"))
                       if isinstance(x, Mapping)],
            age=_int(data.get("age")),
            is_public=data.get("is_public"),
            is_rent=data.get("is_rent"),
            price=data.get("price"),
            created_at=data.get("created_at"),
            image=data.get("image"),
            source=data.get("source"),
            favorite=data.get("favorite"),
            raw=dict(data),
        )


@dataclass
class Service:
    """A service and its current tariff, from ``GET /services`` or ``GET /service/{slug}``.

    ``price.amount`` is per minute of produced audio or video. ``prices`` holds the rates
    charged beside the tariff (for dubbing: ``auto_emotion_per_min``; ``None`` there means
    the feature is not on offer).
    """

    id: Optional[int]
    slug: str
    title: Optional[str]
    price: Optional[Price]
    prices: Dict[str, Optional[Price]] = field(default_factory=dict)
    description: Optional[str] = None
    instruction: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    created_at: Optional[str] = None
    limits: Optional[Dict[str, Any]] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Service:
        return cls(
            id=_int(data.get("id")),
            slug=str(data.get("slug") or ""),
            title=data.get("title"),
            price=Price.maybe(data.get("price")),
            prices={k: Price.maybe(v) for k, v in _map(data.get("prices")).items()},
            description=data.get("description"),
            instruction=data.get("instruction"),
            icon=data.get("icon"),
            color=data.get("color"),
            created_at=data.get("created_at"),
            limits=data.get("limits") if isinstance(data.get("limits"), Mapping) else None,
            raw=dict(data),
        )


@dataclass
class ProjectStatus:
    id: Optional[int]
    title: Optional[str]

    @classmethod
    def from_any(cls, data: Any) -> ProjectStatus:
        if isinstance(data, Mapping):
            return cls(id=_int(data.get("id")), title=data.get("title"))
        return cls(id=_int(data), title=None)

    @property
    def code(self) -> Optional[ProjectStatusCode]:
        try:
            return ProjectStatusCode(self.id) if self.id is not None else None
        except ValueError:
            return None


@dataclass
class Project:
    """A project of any service.

    ``body`` is the service-specific payload as a plain dict (for dubbing: ``speakers``,
    ``chunks``, ``audio_url``, ``export_status``, ...). On an expired project
    (``is_expired``) every url in it is ``None``.

    ``request_id`` (the latest run) and ``words_count`` (speech-to-text) are filled when
    the project was read with ``get_project``.
    """

    id: int
    title: Optional[str]
    status: ProjectStatus
    is_favorite: Optional[bool] = None
    is_expired: bool = False
    expired_at: Optional[str] = None
    is_paid: Optional[bool] = None
    language: Optional[Language] = None
    duration: Optional[float] = None
    price: Optional[Price] = None
    body: Dict[str, Any] = field(default_factory=dict, repr=False)
    request_id: Optional[str] = None
    words_count: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, request_id: Optional[str] = None,
                  words_count: Any = None) -> Project:
        if words_count is None:
            words_count = data.get("words_count")
        return cls(
            id=int(data.get("id") or 0),
            title=data.get("title"),
            status=ProjectStatus.from_any(data.get("status")),
            is_favorite=data.get("is_favorite"),
            is_expired=bool(data.get("is_expired") or False),
            expired_at=data.get("expired_at"),
            is_paid=data.get("is_paid"),
            language=Language.maybe(data.get("language")),
            duration=_float(data.get("duration")),
            price=Price.maybe(data.get("price")),
            body=_map(data.get("body")),
            request_id=request_id,
            words_count=_int(words_count),
            raw=dict(data),
        )

    @property
    def status_code(self) -> Optional[ProjectStatusCode]:
        return self.status.code


@dataclass
class TTSBlock:
    """A text block of a multi-block text-to-speech project (``add-block``)."""

    id: str
    project_id: int
    text: Optional[str]
    sort_order: Optional[int] = None
    speed: Optional[float] = None
    language: Optional[Language] = None
    voice: Optional[Dict[str, Any]] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TTSBlock:
        return cls(
            id=str(data.get("id") or ""),
            project_id=int(data.get("project_id") or 0),
            text=data.get("text"),
            sort_order=_int(data.get("sort_order")),
            speed=_float(data.get("speed")),
            language=Language.maybe(data.get("language")),
            voice=dict(data["voice"]) if isinstance(data.get("voice"), Mapping) else None,
            raw=dict(data),
        )


@dataclass
class SynthesisBlock:
    """Timing of one block inside a finished synthesis (seconds)."""

    block_id: str
    start: Optional[float]
    end: Optional[float]
    duration: Optional[float]
    preview_url: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class Synthesis:
    """State of a text-to-speech run.

    ``preview_url`` is set once ``status`` is ``COMPLETED``. It is the listening copy;
    the downloadable file is obtained with ``client.tts.export()`` /
    ``client.tts.download()``, which charge the balance.
    """

    request_id: str
    status: str
    project_id: Optional[int] = None
    percentage: Optional[int] = None
    preview_url: Optional[str] = None
    duration: Optional[float] = None
    blocks: List[SynthesisBlock] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_completed(self) -> bool:
        return self.status == JobStatus.COMPLETED

    @property
    def is_failed(self) -> bool:
        return self.status == JobStatus.FAILED

    @classmethod
    def from_response(cls, request_id: str, data: Mapping[str, Any],
                      project_id: Optional[int] = None) -> Synthesis:
        blocks: List[SynthesisBlock] = []
        raw_blocks = data.get("blocks")
        if isinstance(raw_blocks, Mapping):
            # The API keys finished blocks by their id.
            items = [(str(k), v) for k, v in raw_blocks.items()]
        else:
            items = [(str(b.get("block_id") or b.get("id") or ""), b)
                     for b in _list(raw_blocks) if isinstance(b, Mapping)]
        for block_id, b in items:
            if not isinstance(b, Mapping):
                continue
            blocks.append(SynthesisBlock(
                block_id=block_id,
                start=_float(b.get("start")),
                end=_float(b.get("end")),
                duration=_float(b.get("duration")),
                preview_url=b.get("preview_url"),
                raw=dict(b),
            ))
        return cls(
            request_id=request_id,
            status=str(data.get("status") or JobStatus.IN_PROGRESS),
            project_id=project_id if project_id is not None else _int(data.get("project_id")),
            percentage=_int(data.get("percentage")),
            preview_url=data.get("preview_url"),
            duration=_float(data.get("duration")),
            blocks=blocks,
            raw=dict(data),
        )


@dataclass
class ExportedFile:
    """A file handed out by an ``export`` call.

    ``free`` is ``True`` when a text-to-speech export used the account's one-time free
    download instead of charging the balance.
    """

    title: Optional[str]
    file: Optional[str]
    free: Optional[bool] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ExportedFile:
        return cls(title=data.get("title"), file=data.get("file"), free=data.get("free"),
                   raw=dict(data))


@dataclass
class STTUpload:
    """Result of ``client.stt.upload()``: the source is stored and quoted, not yet run."""

    project_id: int
    duration: Optional[float]
    preview_url: Optional[str]
    price: Optional[Price]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> STTUpload:
        return cls(project_id=int(data.get("project_id") or 0),
                   duration=_float(data.get("duration")), preview_url=data.get("preview_url"),
                   price=Price.maybe(data.get("price")), raw=dict(data))


@dataclass
class Recognition:
    """A queued speech-to-text run (``recognize`` with ``wait=False``)."""

    project_id: int
    request_id: Optional[str]
    duration: Optional[float]
    price: Optional[Price]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Recognition:
        return cls(project_id=int(data.get("project_id") or 0), request_id=data.get("request_id"),
                   duration=_float(data.get("duration")), price=Price.maybe(data.get("price")),
                   raw=dict(data))


@dataclass
class Segment:
    """One recognised block of a transcript. Times are in seconds."""

    id: Any
    text: str
    start: Optional[float]
    end: Optional[float]
    duration: Optional[float] = None
    original_text: Optional[str] = None
    speaker: Optional[str] = None
    gender: Optional[Gender] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Segment:
        speaker = data.get("speaker")
        return cls(
            id=data.get("id"),
            text=str(data.get("text") or ""),
            start=_float(data.get("start")),
            end=_float(data.get("end")),
            duration=_float(data.get("duration")),
            original_text=data.get("original_text"),
            speaker=str(speaker) if speaker is not None else None,
            gender=Gender.from_dict(data.get("gender")),
            raw=dict(data),
        )


@dataclass
class Transcript:
    """A speech-to-text result."""

    project_id: int
    status: ProjectStatus
    segments: List[Segment]
    percentage: Optional[int] = None
    duration: Optional[float] = None
    language: Optional[Language] = None
    words_count: Optional[int] = None
    price: Optional[Price] = None
    project: Optional[Project] = field(default=None, repr=False)

    @property
    def text(self) -> str:
        """The whole transcript, one segment per line."""
        return "\n".join(s.text.strip() for s in self.segments if s.text and s.text.strip())

    @property
    def is_completed(self) -> bool:
        return self.status.id in (ProjectStatusCode.COMPLETED, ProjectStatusCode.ORDERED)

    @property
    def is_failed(self) -> bool:
        return self.status.id == ProjectStatusCode.REJECTED

    @classmethod
    def from_project(cls, project: Project) -> Transcript:
        return cls(
            project_id=project.id,
            status=project.status,
            segments=[Segment.from_dict(b) for b in _list(project.body.get("blocks"))
                      if isinstance(b, Mapping)],
            percentage=_int(project.body.get("percentage")),
            duration=project.duration,
            language=project.language,
            words_count=project.words_count,
            price=project.price,
            project=project,
        )


@dataclass
class DubbingDraft:
    """A new dubbing project (``client.dubbing.create()``). Nothing has been charged."""

    project_id: int
    price: Optional[Price]
    project: Optional[Project]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DubbingDraft:
        project = data.get("project")
        return cls(project_id=int(data.get("project_id") or 0),
                   price=Price.maybe(data.get("price")),
                   project=Project.from_dict(project) if isinstance(project, Mapping) else None,
                   raw=dict(data))


@dataclass
class DubbingRun:
    """A queued dubbing run (preview, full dub, render or one re-recorded line).

    ``price`` is what this run costs (``None`` when it is free); the counters tell how
    many free previews/renders the project has used.
    """

    request_id: str
    price: Optional[Price] = None
    previews_used: Optional[int] = None
    free_previews: Optional[int] = None
    renders_used: Optional[int] = None
    free_renders: Optional[int] = None
    chunk: Optional[Dict[str, Any]] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DubbingRun:
        return cls(
            request_id=str(data.get("request_id") or ""),
            price=Price.maybe(data.get("price")),
            previews_used=_int(data.get("previews_used")),
            free_previews=_int(data.get("free_previews")),
            renders_used=_int(data.get("renders_used")),
            free_renders=_int(data.get("free_renders")),
            chunk=dict(data["chunk"]) if isinstance(data.get("chunk"), Mapping) else None,
            raw=dict(data),
        )


@dataclass
class DubbingStatus:
    """State of a dubbing run (``GET /services/dubbing/get-response/{requestId}``).

    ``audio_url`` is the watermarked listening copy of the soundtrack. Use
    ``client.dubbing.download()`` for the clean files.
    """

    request_id: str
    status: str
    stage: Optional[str] = None
    percentage: Optional[int] = None
    audio_url: Optional[str] = None
    video_url: Optional[str] = None
    preview_audio_url: Optional[str] = None
    duration_ms: Optional[int] = None
    source_lang: Optional[str] = None
    speakers: Optional[List[Dict[str, Any]]] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_completed(self) -> bool:
        return self.status == JobStatus.COMPLETED

    @property
    def is_failed(self) -> bool:
        return self.status == JobStatus.FAILED

    @classmethod
    def from_response(cls, request_id: str, data: Mapping[str, Any]) -> DubbingStatus:
        speakers = data.get("speakers")
        return cls(
            request_id=request_id,
            status=str(data.get("status") or JobStatus.IN_PROGRESS),
            stage=data.get("stage"),
            percentage=_int(data.get("percentage")),
            audio_url=data.get("audio_url"),
            video_url=data.get("video_url"),
            preview_audio_url=data.get("preview_audio_url"),
            duration_ms=_int(data.get("duration_ms")),
            source_lang=data.get("source_lang"),
            speakers=list(speakers) if isinstance(speakers, list) else None,
            raw=dict(data),
        )


@dataclass
class DubbingExport:
    """Result of ``POST /services/dubbing/export/{projectId}``.

    When ``pending`` is ``True`` the mp4 is still being assembled (HTTP ``202``):
    ``request_id`` identifies the assembly and ``file``/``audio`` are ``None``. Otherwise
    ``file`` is the clean mp4 and ``audio`` the clean soundtrack - or, when
    ``audio_only`` is ``True`` (a project made from an audio file), both are the dubbed
    mp3. Use the urls exactly as given (they carry a ``?v=`` cache-buster).
    """

    pending: bool
    title: Optional[str] = None
    file: Optional[str] = None
    audio: Optional[str] = None
    request_id: Optional[str] = None
    audio_only: bool = False
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], status_code: int = 200) -> DubbingExport:
        pending = bool(data.get("pending")) or status_code == 202
        return cls(pending=pending, title=data.get("title"), file=data.get("file"),
                   audio=data.get("audio"), request_id=data.get("request_id"),
                   audio_only=bool(data.get("audio_only")), raw=dict(data))


@dataclass
class DubbingFormats:
    """Accepted source formats and background modes for dubbing."""

    formats: List[str]
    background_modes: Dict[str, str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DubbingFormats:
        return cls(formats=[str(x) for x in _list(data.get("formats"))],
                   background_modes={str(k): str(v)
                                     for k, v in _map(data.get("background_modes")).items()},
                   raw=dict(data))
