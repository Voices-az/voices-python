"""Official Python client for the Voices.az API.

Text-to-speech, speech-to-text and video dubbing over HTTP::

    import voices_az

    client = voices_az.Client()          # reads VOICES_API_KEY
    result = client.tts.synthesize("Salam, dünya!", language="az")
    print(result.preview_url)

Documentation: https://voices.az/docs
"""

from . import types
from ._client import AsyncClient, Client
from ._version import __version__
from .exceptions import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    ContentPolicyError,
    IdempotencyInProgressError,
    InsufficientBalanceError,
    JobFailedError,
    NotFoundError,
    PayloadTooLargeError,
    PermissionDeniedError,
    ProjectExpiredError,
    RateLimitError,
    ServerError,
    TimeoutError,
    ValidationError,
    VoicesError,
)

__all__ = [
    "__version__",
    "Client",
    "AsyncClient",
    "types",
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
