# voices-az - официальный клиент для Python

Официальная Python-библиотека для API [Voices.az](https://voices.az): синтез речи
(text-to-speech), распознавание речи (speech-to-text) и дубляж видео.

Полная документация (на английском): [README.md](../README.md) · HTTP API:
<https://voices.az/docs>

## Установка

```bash
pip install voices-az
```

Поддерживается Python 3.9 и новее.

## API-ключ

Ключ создаётся, обновляется и отзывается в панели: **[app.voices.az](https://app.voices.az)
→ Профиль → API-ключ**. Новый ключ показывается только один раз - сохраните его сразу.
Передайте ключ явно или через переменную окружения `VOICES_API_KEY`:

```bash
export VOICES_API_KEY=vz_live_...
```

Держите ключ в секрете: любой, у кого он есть, может тратить ваш баланс. Не публикуйте его
в браузере и в клиентском коде.

## Синтез речи

```python
import voices_az

with voices_az.Client() as client:
    result = client.tts.synthesize("Salam! Bu mətn Voices.az ilə səsləndirilib.",
                                   language="az", voice=41)
    print(result.preview_url)                            # прослушивание, бесплатно
    client.tts.download(result.project_id, "salam.mp3")   # списывает с баланса
```

В тексте можно использовать теги `[PAUSE=1.5]`, `[LAUGH]`, `[SIGH]`, `[UHM]`, `[SHH]`.
Список голосов: `client.voices.list(language="az")`.

## Распознавание речи

```python
transcript = client.stt.recognize("interview.mp3", language="ru", speakers=2)
print(transcript.text)
client.stt.download(transcript.project_id, "interview.srt", format="srt")
```

Для видео с YouTube используйте параметр `youtube_url=`.

## Дубляж

```python
draft = client.dubbing.create(youtube_url="https://www.youtube.com/watch?v=...",
                              target_language="az")
run = client.dubbing.generate(draft.project_id)     # списывает с баланса
client.dubbing.wait(run.request_id)
client.dubbing.download(draft.project_id, "dubbed.mp4")
```

## Оплата

API работает по тем же поминутным тарифам, что и панель, и списывает с того же баланса:

- синтез - при первом скачивании файла (`tts.export()` / `tts.download()`);
- распознавание - при запуске (`stt.recognize()` / `stt.generate()`);
- дубляж - при запуске полного дубляжа (`dubbing.generate()`); первые несколько превью и
  пересборок бесплатны.

Если баланса не хватает, возникает `InsufficientBalanceError`, ничего не списывается; поле
`missing` показывает недостающую сумму.

## Ошибки

Все исключения наследуются от `voices_az.VoicesError`: `AuthenticationError` (401),
`PermissionDeniedError` (403), `NotFoundError` (404), `ProjectExpiredError` (410),
`ValidationError` (422), `InsufficientBalanceError`, `ContentPolicyError`, `RateLimitError`
(429), `ServerError` (5xx), `JobFailedError`, `voices_az.TimeoutError`. Язык сообщений об
ошибках: `Client(language="ru")`.

## Асинхронный клиент

`voices_az.AsyncClient` имеет те же методы, их нужно вызывать через `await`.

## Лицензия

MIT.
