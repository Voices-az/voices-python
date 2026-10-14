"""Exceptions raised by the Voices.az client.

Every exception derives from :class:`VoicesError`, so ``except VoicesError`` catches
anything the client raises on purpose. Errors that come from an HTTP response are
:class:`APIStatusError` subclasses and carry the status code, the machine-readable
``type`` slug the API sends (``error.type``) and the raw response body.

Branch on the exception class or on :attr:`APIStatusError.type`, never on the message:
messages are localised (see the ``language`` option of the client).
"""

from __future__ import annotations

import builtins
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, Optional

import httpx

__all__ = [
    "VoicesError",
    "APIConnectionError",
    "APITimeoutError",
    "APIStatusError",
    "BadRequestError",
    "AuthenticationError",
    "PermissionDeniedError",
    "NotFoundError",
    "ConflictError",
    "IdempotencyInProgressError",
    "ProjectExpiredError",
    "PayloadTooLargeError",
    "ValidationError",
    "InsufficientBalanceError",
    "ContentPolicyError",
    "RateLimitError",
    "ServerError",
    "JobFailedError",
    "TimeoutError",
]


class VoicesError(Exception):
    """Base class of every error raised by this package."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class APIConnectionError(VoicesError):
    """The API could not be reached (DNS, TCP, TLS, connection reset, ...).

    Raised after the client's own retries are exhausted, or immediately for a request
    that is not safe to repeat.
    """

    def __init__(self, message: str = "Could not connect to the Voices.az API.", *,
                 request: Optional[httpx.Request] = None) -> None:
        super().__init__(message)
        self.request = request


class APITimeoutError(APIConnectionError):
    """The HTTP request timed out (see the ``timeout`` option of the client)."""

    def __init__(self, message: str = "The request to the Voices.az API timed out.", *,
                 request: Optional[httpx.Request] = None) -> None:
        super().__init__(message, request=request)


class APIStatusError(VoicesError):
    """The API answered with an error status.

    Attributes:
        status_code: HTTP status of the response.
        type: The stable machine-readable slug from ``error.type`` (for example
            ``"not_found"``, ``"gone"``, ``"api_key_scope"``), or ``None`` when the
            response did not carry one.
        data: ``error.data`` (or the top-level ``data`` of a validation failure), if any.
        body: The decoded JSON body, or ``None`` when the body was not JSON.
        response: The underlying :class:`httpx.Response`.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        type: Optional[str] = None,
        data: Optional[Any] = None,
        body: Optional[Any] = None,
        response: Optional[httpx.Response] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.type = type
        self.data = data
        self.body = body
        self.response = response

    @property
    def headers(self) -> Mapping[str, str]:
        return self.response.headers if self.response is not None else {}

    def __str__(self) -> str:
        suffix = f", type={self.type}" if self.type else ""
        return f"{self.message} (HTTP {self.status_code}{suffix})"


class BadRequestError(APIStatusError):
    """``400`` - the request was malformed."""


class AuthenticationError(APIStatusError):
    """``401`` - the API key is missing, unknown or revoked, or the account is not active.

    Also raised when a key is sent in the query string, which the API refuses on
    purpose. This client always sends the key in the ``X-API-KEY`` header.
    """


class PermissionDeniedError(APIStatusError):
    """``403`` - the key is valid but may not call this endpoint.

    ``type == "api_key_scope"`` means the endpoint is a panel-only operation that an API
    key can never call.
    """


class NotFoundError(APIStatusError):
    """``404`` - no such resource, or it belongs to another account."""


class ConflictError(APIStatusError):
    """``409`` - the request conflicts with the current state."""


class IdempotencyInProgressError(ConflictError):
    """``409 idempotency_in_progress`` - a request with the same ``Idempotency-Key`` is
    still running. Retrying with the same key later replays its response."""


class ProjectExpiredError(APIStatusError):
    """``410`` - the project outlived its retention window and its files were deleted.

    The project itself can still be read, listed, renamed and deleted; only the calls that
    act on its files are refused. Retrying never helps.

    Attributes:
        project_id: The project whose files are gone, when the API reports it.
        expired_at: When the files were deleted (ISO-8601 string), when reported.
    """

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        data = self.data if isinstance(self.data, Mapping) else {}
        self.project_id: Optional[int] = _int_or_none(data.get("project_id"))
        self.expired_at: Optional[str] = data.get("expired_at")


class PayloadTooLargeError(APIStatusError):
    """``413`` - the uploaded file is larger than the service accepts."""


class ValidationError(APIStatusError):
    """``422`` - the request did not pass validation.

    Attributes:
        errors: Field errors as ``{"field": ["message", ...]}``. Empty when the API only
            sent a single message.
    """

    def __init__(self, message: str, *, errors: Optional[Dict[str, List[str]]] = None,
                 **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.errors: Dict[str, List[str]] = dict(errors or {})


class InsufficientBalanceError(ValidationError):
    """``422`` - the balance does not cover the operation. Nothing was charged or queued.

    Attributes:
        price: What the operation costs.
        balance: The balance it was checked against.
        missing: The amount to top up (the API may round it up to its minimum top-up).
        currency: Currency of the three amounts (``"AZN"``).
        project_id: The project the operation was for, when there is one.
        reason: ``"insufficient_balance"`` when the API sent the figures.
    """

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        data = self.data if isinstance(self.data, Mapping) else {}
        self.reason: Optional[str] = data.get("reason")
        self.price: Optional[Decimal] = _decimal_or_none(data.get("price"))
        self.balance: Optional[Decimal] = _decimal_or_none(data.get("balance"))
        self.missing: Optional[Decimal] = _decimal_or_none(data.get("missing"))
        self.currency: Optional[str] = data.get("currency")
        self.project_id: Optional[int] = _int_or_none(data.get("project_id"))


class ContentPolicyError(APIStatusError):
    """``422 content_policy`` - the text or the result was refused by the content policy.

    The message is deliberately neutral; nothing was charged.
    """


class RateLimitError(APIStatusError):
    """``429`` - over the per-key request budget.

    Attributes:
        retry_after: Seconds to wait before the next request (from ``Retry-After``).
        limit: ``X-RateLimit-Limit``, when sent.
        remaining: ``X-RateLimit-Remaining``, when sent.
    """

    def __init__(self, message: str, *, retry_after: Optional[float] = None,
                 **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after
        headers = self.headers
        self.limit: Optional[int] = _int_or_none(headers.get("x-ratelimit-limit"))
        self.remaining: Optional[int] = _int_or_none(headers.get("x-ratelimit-remaining"))


class ServerError(APIStatusError):
    """``5xx`` - the API failed. Charging calls are never stored as replays on a ``5xx``,
    so repeating them with the same ``Idempotency-Key`` runs them for real."""


class JobFailedError(VoicesError):
    """A queued run (synthesis, recognition, dubbing) finished with a failure status.

    Attributes:
        request_id: The run id, when known.
        project_id: The project, when known.
        status: The final status reported by the API (``"FAILED"`` or ``"Rejected"``).
        result: The last decoded status payload.
    """

    def __init__(self, message: str, *, request_id: Optional[str] = None,
                 project_id: Optional[int] = None, status: Optional[str] = None,
                 result: Any = None) -> None:
        super().__init__(message)
        self.request_id = request_id
        self.project_id = project_id
        self.status = status
        self.result = result


class TimeoutError(VoicesError, builtins.TimeoutError):
    """A ``wait``/``wait=True`` helper gave up before the run finished.

    The run itself keeps going on the server: poll it again later with the ids carried
    here.

    Attributes:
        request_id: The run id, when known.
        project_id: The project, when known.
        last: The last status payload seen before giving up.
    """

    def __init__(self, message: str, *, request_id: Optional[str] = None,
                 project_id: Optional[int] = None, last: Any = None) -> None:
        super().__init__(message)
        self.request_id = request_id
        self.project_id = project_id
        self.last = last


def _decimal_or_none(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _int_or_none(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
