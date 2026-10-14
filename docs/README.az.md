# voices-az - Python üçün rəsmi müştəri

[Voices.az](https://voices.az) API-si üçün rəsmi Python kitabxanası: mətnin səsləndirilməsi
(text-to-speech), nitqin mətnə çevrilməsi (speech-to-text) və videoların dublyajı.

Tam sənədləşmə (ingilis dilində): [README.md](../README.md) · HTTP API:
<https://voices.az/docs>

## Quraşdırma

```bash
pip install voices-az
```

Python 3.9 və daha yeni versiyalar dəstəklənir.

## API açarı

Açarı panelin **[app.voices.az](https://app.voices.az) → Profil → API açar** bölməsində
yarada, yeniləyə və ya ləğv edə bilərsiniz. Yeni açar yalnız bir dəfə göstərilir - onu dərhal
saxlayın. Açarı `VOICES_API_KEY` mühit dəyişəninə yazın və ya birbaşa ötürün:

```bash
export VOICES_API_KEY=vz_live_...
```

Açarı məxfi saxlayın: ona sahib olan hər kəs balansınızdan istifadə edə bilər. Açarı
brauzerdə və ya müştəri tərəfindəki kodda yerləşdirməyin.

## Mətnin səsləndirilməsi

```python
import voices_az

with voices_az.Client() as client:
    result = client.tts.synthesize("Salam! Bu mətn Voices.az ilə səsləndirilib.",
                                   language="az", voice=41)
    print(result.preview_url)                          # dinləmək üçün, pulsuz
    client.tts.download(result.project_id, "salam.mp3")   # balansdan ödənilir
```

Mətndə `[PAUSE=1.5]`, `[LAUGH]`, `[SIGH]`, `[UHM]`, `[SHH]` teqlərindən istifadə etmək olar.
Səslərin siyahısı: `client.voices.list(language="az")`.

## Nitqin mətnə çevrilməsi

```python
transcript = client.stt.recognize("musahibe.mp3", language="az", speakers=2)
print(transcript.text)
client.stt.download(transcript.project_id, "musahibe.srt", format="srt")
```

YouTube videosu üçün `youtube_url=` parametrindən istifadə edin.

## Dublyaj

```python
draft = client.dubbing.create(youtube_url="https://www.youtube.com/watch?v=...",
                              target_language="az")
run = client.dubbing.generate(draft.project_id)     # balansdan ödənilir
client.dubbing.wait(run.request_id)
client.dubbing.download(draft.project_id, "dublyaj.mp4")
```

## Ödəniş

API paneldəki eyni dəqiqəlik tariflərlə işləyir və məbləğ eyni balansdan çıxılır:

- səsləndirmə - faylın ilk yüklənməsində (`tts.export()` / `tts.download()`);
- nitqin tanınması - tanınma başlayanda (`stt.recognize()` / `stt.generate()`);
- dublyaj - tam dublyaj başlayanda (`dubbing.generate()`); ilk bir neçə önizləmə və
  yenidən montaj pulsuzdur.

Balans çatmayanda `InsufficientBalanceError` yaranır, heç nə ödənilmir; `missing` sahəsi
çatışmayan məbləği göstərir.

## Xətalar

Bütün istisnalar `voices_az.VoicesError` sinfindən törəyir: `AuthenticationError` (401),
`PermissionDeniedError` (403), `NotFoundError` (404), `ProjectExpiredError` (410),
`ValidationError` (422), `InsufficientBalanceError`, `ContentPolicyError`, `RateLimitError`
(429), `ServerError` (5xx), `JobFailedError`, `voices_az.TimeoutError`. Xəta mesajlarının dili:
`Client(language="az")`.

## Asinxron istifadə

`voices_az.AsyncClient` eyni metodlara malikdir, sadəcə `await` ilə çağırılır.

## Lisenziya

MIT.
