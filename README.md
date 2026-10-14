# voices-az

The official Python client for the [Voices.az](https://voices.az) API: text-to-speech,
speech-to-text and video dubbing, with Azerbaijani first.

- One call to synthesize, transcribe or dub - the client waits for the result for you.
- Sync and `asyncio` clients with the same methods.
- Typed results (dataclasses), typed errors, safe automatic retries.
- Large files are streamed from disk, never loaded into memory.
- Python 3.9+, one dependency (`httpx`).

Documentation of the HTTP API: <https://voices.az/docs>

Also in: [Azərbaycan dili](docs/README.az.md) · [Русский](docs/README.ru.md)

## Install

```bash
pip install voices-az
```

## Authentication

Every request is made with your account's API key. Find it in the panel at
**[app.voices.az](https://app.voices.az) → Profile → API key**: create the key there
(or rotate / revoke it). A new key is shown only once - store it right away.

Pass the key explicitly, or set the `VOICES_API_KEY` environment variable:

```bash
export VOICES_API_KEY=vz_live_...
```

```python
import voices_az

client = voices_az.Client()                      # reads VOICES_API_KEY
client = voices_az.Client(api_key="vz_live_...")  # or explicitly
```

Keep the key on the server side: anyone who has it can spend your balance. The client
always sends it in the `X-API-KEY` header (never in a URL), and never sends it to the
file-storage links it downloads from.

## Text-to-speech

```python
import voices_az

with voices_az.Client() as client:
    result = client.tts.synthesize(
        "Salam! Bu mətn Voices.az ilə səsləndirilib.",
        language="az",   # a language code or id
        voice=41,        # a voice id, see client.voices.list()
        speed=1,         # 1, 1.5, 2, 2.5 or 3
    )
    print(result.preview_url)   # a listening copy, free
    print(result.duration)      # seconds

    # Charges the balance, then saves the MP3:
    client.tts.download(result.project_id, "salam.mp3")
```

`synthesize()` queues the text and polls until the audio is ready (`wait=False` returns
right away; call `client.tts.wait(request_id)` later). The text may contain inline tags:
`[PAUSE=1.5]`, `[LAUGH]`, `[SIGH]`, `[UHM]`, `[SHH]`.

Multi-block projects: `client.tts.add_block()`, `update_block()`, `delete_block()`, then
`client.tts.generate(project_id, wait=True)`.

### Voices and languages

```python
for language in client.languages.list():
    print(language.id, language.code, language.title)

for voice in client.voices.iter(language="az", gender="female"):
    print(voice.id, voice.full_name)
```

## Speech-to-text

```python
transcript = client.stt.recognize("interview.mp3", language="az", speakers=2)
print(transcript.text)
for segment in transcript.segments:
    print(f"{segment.start:.2f}-{segment.end:.2f} {segment.text}")

# Subtitles or plain text: txt, srt, vtt, sbv, dfxp, csv
client.stt.download(transcript.project_id, "interview.srt", format="srt")
```

`file=` takes a path, `bytes` or a binary file object; use `youtube_url=` for a YouTube
video. Options: `speakers` (1-10), `remove_background=True` (strip music and noise first),
`convert_numbers=True` (digits instead of words).

To see the price before paying, upload first and start later:

```python
upload = client.stt.upload("interview.mp3")
print(upload.duration, upload.price)
client.stt.generate(upload.project_id, language="az")   # charges the balance
transcript = client.stt.wait(upload.project_id)
```

## Dubbing

```python
draft = client.dubbing.create(
    youtube_url="https://www.youtube.com/watch?v=...",   # or file="video.mp4"
    target_language="az",
    background_mode="duck",       # or "separate": keep music and effects at full level
)
print(draft.project_id, draft.price)    # the quote; nothing is charged yet

preview = client.dubbing.preview(draft.project_id)           # the first seconds
print(client.dubbing.wait(preview.request_id).audio_url)

run = client.dubbing.generate(draft.project_id)              # charges the balance
client.dubbing.wait(run.request_id)

client.dubbing.download(draft.project_id, "dubbed.mp4", audio_path="dubbed.mp3")
```

`download()` asks for the clean (watermark-free) files and, when the video still has to be
assembled, waits for it. Choose a voice per speaker with
`generate(..., voice_map={"SPEAKER_00": 41})` - the speaker keys are in
`client.dubbing.get_project(id).body["speakers"]`. Edit single lines with `add_chunk()`,
`update_chunk()`, `delete_chunk()`, `regenerate_chunk()`, then `render()`.

## Async

`AsyncClient` has exactly the same methods, awaitable:

```python
import asyncio
import voices_az

async def main() -> None:
    async with voices_az.AsyncClient() as client:
        result = await client.tts.synthesize("Salam!", language="az")
        await client.tts.download(result.project_id, "salam.mp3")

        async for voice in client.voices.iter(language="az"):
            print(voice.full_name)

asyncio.run(main())
```

## What costs money

The API bills at the same per-minute rates as the panel (`client.services.list()` shows
them) and takes the money from the same balance (`client.account.balance()`).

| Call | Charges the balance |
| --- | --- |
| `tts.synthesize()`, `tts.generate()` | No |
| `tts.export()`, `tts.download()` | **Yes**, on the first export of a project; exporting it again is free |
| `stt.recognize()`, `stt.generate()` | **Yes**, when recognition starts |
| `stt.upload()`, `stt.export()`, `stt.download()` | No |
| `dubbing.create()` | No |
| `dubbing.preview()`, `dubbing.render()` | The first few per project are free, then each one is charged (`price` on the result) |
| `dubbing.generate()` | **Yes**, the whole dub (plus the auto-emotion surcharge when it is on) |
| `dubbing.regenerate_chunk()` | **Yes** (`price` on the result) |
| `dubbing.export()`, `dubbing.download()` | No for dubs paid on `generate()` |

When the balance is too low the call raises `InsufficientBalanceError` and nothing is
charged or queued; `missing` tells how much to top up.

## Errors

Every exception derives from `voices_az.VoicesError`:

| Exception | When |
| --- | --- |
| `AuthenticationError` | 401 - missing, unknown or revoked API key |
| `PermissionDeniedError` | 403 - the key may not call this endpoint (`type == "api_key_scope"`) |
| `NotFoundError` | 404 - no such project (or it belongs to another account) |
| `ConflictError`, `IdempotencyInProgressError` | 409 |
| `ProjectExpiredError` | 410 - the project's files were deleted after the retention window (`project_id`, `expired_at`) |
| `PayloadTooLargeError` | 413 - the file is over the upload limit |
| `ValidationError` | 422 - invalid input; `errors` holds `{"field": ["message"]}` |
| `InsufficientBalanceError` | 422 - `price`, `balance`, `missing`, `currency`, `project_id` (a `ValidationError`) |
| `ContentPolicyError` | 422 - the text or result was refused by the content policy |
| `RateLimitError` | 429 - `retry_after`, `limit`, `remaining` |
| `ServerError` | 5xx |
| `APIConnectionError`, `APITimeoutError` | the API could not be reached / the request timed out |
| `JobFailedError` | a synthesis, recognition or dubbing run failed |
| `voices_az.TimeoutError` | a `wait` helper gave up; the run continues on the server |

HTTP errors carry `status_code`, `type` (the API's stable `error.type` slug), `message`,
`data` and the raw `body`. Messages are localised; pick their language with
`Client(language="az" | "en" | "ru" | "tr")`, and branch on the class or `type`, not on the
message.

```python
try:
    client.tts.download(project_id, "out.mp3")
except voices_az.InsufficientBalanceError as exc:
    print(f"Top up {exc.missing} {exc.currency} at https://app.voices.az")
except voices_az.ProjectExpiredError:
    print("The files of this project are no longer stored.")
```

## Retries and idempotency

Failed requests are repeated (`max_retries=2` by default, exponential backoff) only when
that cannot charge twice:

- reads (`GET`) on network errors and on `502`/`503`/`504`;
- any request when the connection could not be opened at all, or on `429` (after
  `Retry-After`; a wait longer than a minute raises `RateLimitError` instead);
- the calls that queue paid work (`synthesize`, `recognize`, `generate`, `preview`,
  `render`, ...): the client sends an `Idempotency-Key` with them, so the API replays
  the first answer instead of running and charging again. Pass your own key with
  `idempotency_key=...` to make a retry safe across processes too.

`export` is never repeated automatically: it can charge and the API does not accept an
idempotency key there.

## Polling, limits and retention

- The `wait` helpers poll every 2 seconds (`poll_interval`, never less) and give up after
  `wait_timeout` seconds (`None` waits indefinitely). `on_progress` receives every status.
- The API allows 60 requests a minute and 5000 a day per key.
- Files are kept for 6 months after the last activity on a project (30 days for a dubbing
  project that was only previewed). Afterwards the project still exists but its file calls
  raise `ProjectExpiredError` - download what you need in time.

## Configuration

```python
client = voices_az.Client(
    api_key="vz_live_...",            # default: VOICES_API_KEY
    base_url="https://voices.az/api",  # default (or VOICES_BASE_URL)
    timeout=120,                      # seconds, or an httpx.Timeout
    max_retries=2,
    language="en",                    # language of error messages
    poll_interval=2,
    http_client=None,                 # your own httpx.Client (proxies, TLS, ...)
)
```

Every result keeps the decoded JSON in `.raw`, and `client.request("GET", "/services")`
calls any endpoint directly.

## Examples

Runnable scripts in [`examples/`](examples): `tts_to_file.py`, `transcribe_file.py`,
`dub_youtube.py`. Each reads `VOICES_API_KEY`.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q
ruff check .
mypy
```

The tests never touch the network.

## License

MIT - see [LICENSE](LICENSE).
