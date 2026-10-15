# Changelog

## Unreleased

API note, no SDK change needed: from the Voices.az server update planned for October 2026,
paginated lists in the standard `links` / `meta` shape (`GET /customer/transactions`)
carry a new integer field `page` in every `meta.links[]` entry (`null` for a previous /
next link that leads nowhere). The SDK builds `Page` from `current_page`, `last_page`,
`per_page` and `total` only, so its behaviour does not change; the new field is visible
in `Page.raw`.

## 0.2.0 - 2026-10-15

Follows the Voices.az API update of 2026-10-15. Deploy order: the API first - this version
sends the new field names below, which older API versions do not know.

- `tts.add_block()` takes `voice`, `language` and `speed`, so a multi-block project can
  mix voices; `tts.update_block()` takes `voice`.
- New `tts.sort_blocks()` and `tts.duplicate_block()`.
- New `voices.page()`: a voice page with its pagination figures (`total`, `last_page`,
  `has_more`). `voices.iter()` follows them, uses the real page size (24), and stops
  instead of looping when a server answers every page with the same voices.
- Dubbing: `DubbingExport.audio_only`; `download()` saves the dubbed mp3 of a project made
  from an audio file (as `.mp3`).
- Wire names: `background_mode="separate"` and the speech-to-text `remove_background`
  field are sent under their public names. The former spelling of `separate` is still
  accepted as input and sent as `separate`.

## 0.1.0 - 2026-10-14

First release.

- `Client` and `AsyncClient` covering every operation of the public Voices.az API:
  text-to-speech, speech-to-text, dubbing, voices, languages, services and the account
  balance.
- Helpers that wait for results: `tts.synthesize()`, `stt.recognize()`,
  `dubbing.wait()`, `dubbing.download()`.
- Typed results and errors, automatic `Idempotency-Key` on paid calls, safe retries,
  streamed uploads and downloads.
