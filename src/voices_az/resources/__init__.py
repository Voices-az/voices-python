"""API resources (``client.tts``, ``client.stt``, ``client.dubbing``, ...)."""

from .account import Account, AsyncAccount
from .catalogue import AsyncLanguages, AsyncServices, AsyncVoices, Languages, Services, Voices
from .dubbing import AsyncDubbing, Dubbing
from .stt import STT, AsyncSTT
from .tts import TTS, AsyncTTS

__all__ = [
    "TTS",
    "AsyncTTS",
    "STT",
    "AsyncSTT",
    "Dubbing",
    "AsyncDubbing",
    "Voices",
    "AsyncVoices",
    "Languages",
    "AsyncLanguages",
    "Services",
    "AsyncServices",
    "Account",
    "AsyncAccount",
]
