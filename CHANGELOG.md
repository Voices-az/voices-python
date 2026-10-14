# Changelog

## 0.1.0 - 2026-10-14

First release.

- `Client` and `AsyncClient` covering every operation of the public Voices.az API:
  text-to-speech, speech-to-text, dubbing, voices, languages, services and the account
  balance.
- Helpers that wait for results: `tts.synthesize()`, `stt.recognize()`,
  `dubbing.wait()`, `dubbing.download()`.
- Typed results and errors, automatic `Idempotency-Key` on paid calls, safe retries,
  streamed uploads and downloads.
