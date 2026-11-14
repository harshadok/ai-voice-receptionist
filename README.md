# AI Voice Receptionist

An English voice/text receptionist with local speech recognition, speech synthesis, model-selected tool calls, and a persistent demo appointment API.

**Implemented local portfolio application**, with source, persistent storage, runnable API, synthetic examples, automated tests, and a demo script. The interactive API at `/docs` is the included client. This repository does not claim a production deployment, a native mobile client, or previously measured customer usage.

## Features

- WAV speech-to-text using Whisper on the backend CPU; no uploaded audio is sent to a cloud model.
- Text-to-speech with macOS `say` or Linux `espeak-ng`; generated WAV responses can be downloaded.
- Validated, allowlisted structured tool calls: answer a question, list availability, propose a booking, cancel a pending proposal.
- Explicit confirmation tokens, ten-minute proposal expiry, slot conflict checks, and payload-bound idempotency.
- SQLite session history and bookings survive restarts.
- Built-in business API, plus an HTTP client for an independently hosted compatible business API.

## Install and run

Use Python 3.9–3.12 (developed/tested here with 3.9.6; Python 3.11 is recommended for a new environment).

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

For AI operations, install [Ollama](https://ollama.com/download), start its local server, and pull a model:

```sh
ollama serve
# In a second terminal:
ollama pull qwen2.5:1.5b
export AI_MODEL=qwen2.5:1.5b
./scripts/start.sh
```

Open [interactive API docs](http://127.0.0.1:8101/docs). The default service port is 8101; override with `PORT`. Keep one API worker bound to localhost. This single-user application has no authentication and stores development data in ignored `data/`; do not expose it as a multi-user public service.

Configuration is read from environment variables. `.env.example` documents them but is not automatically executed or loaded. `OLLAMA_BASE_URL` defaults to `http://127.0.0.1:11434`; `AI_MODEL` selects the installed local model. Providers run on the backend computer; the initial model downloads need internet. No paid API credentials are required.

`requirements.txt` contains portable version ranges; `requirements-lock.txt`, when present, records the exact versions installed in this macOS development environment.

## Walkthrough

1. `POST /sessions` creates a session; retain its `id`.
2. `POST /sessions/{id}/turns` with `{"text":"What are your opening hours?","speak":true}` returns a tool result and optional speech URL.
3. Alternatively, upload a WAV to `POST /sessions/{id}/audio`; the transcript is passed through the same tool dispatcher.
4. Read `/business/availability?day=YYYY-MM-DD`. Request a proposal through a text turn, including a valid slot, name and contact.
5. Inspect `pending`, then explicitly call `POST /sessions/{id}/confirm` with its `confirmation_token` and a stable `idempotency_key`.
6. Retrying the same confirmation returns the original booking. A proposal alone never books a slot.
7. `POST /speech` converts a supplied text to a WAV; `GET /audio/{id}` serves a saved spoken reply.

With the API running, execute the synthetic walkthrough in another terminal:

```sh
source .venv/bin/activate
python scripts/demo.py
```

Use `--url http://127.0.0.1:PORT` to target a different local port. `/docs` exposes the full request and response schemas for manual testing.

## Tests

```sh
python -m pytest -q
```

The current automated suite has **5 passing tests** covering workflow behaviour and important failures. Tests inject provider doubles to remain deterministic; `VERIFICATION.md` separately records real-provider checks. Automated CI runs the deterministic suite without model credentials. The synthetic demo is not a production accuracy benchmark.

## Speech and business configuration

The first transcription downloads the configured Whisper weights into `data/models`. `WHISPER_MODEL=tiny.en` is the default. macOS needs its built-in `say`; Linux needs `espeak-ng`. No ffmpeg is required for the supported PCM WAV input path.

`BUSINESS_TIMEZONE` defaults to `Asia/Kolkata`. To use an external compatible API, export `BUSINESS_API_URL=http://127.0.0.1:8105/business`. The bundled `/business` endpoints define the contract. The adapter sends a stable idempotency key on appointment requests and surfaces conflicts/provider failures. Keep external demo providers separate from any real customer booking system.

Modules: `app/speech.py` handles real STT/TTS, `app/business.py` implements the booking API and HTTP adapter, `app/main.py` coordinates sessions and tools.

## Operational boundaries

- English transcription; PCM WAV only, 16-bit mono/stereo, 8–48 kHz, maximum 60 seconds and 10 MB. Audio is resampled locally to 16 kHz. No microphone capture or telephone carrier integration is included.
- The default business is a synthetic consulting studio, weekdays with fixed appointment slots in `Asia/Kolkata`. No email, SMS, calls, or real external calendar changes are performed.
- The model chooses structured tool invocations; the server validates and executes them. It cannot use arbitrary tools or confirm a booking itself. Model-written FAQ answers still need review.
- Run a single API worker: the session proposal/confirmation coordinator is protected by a process-local lock. Database uniqueness enforces booking conflicts and idempotency.
- Audio replies are stored under `data/audio`; session transcripts/contact details are stored locally. Remove development data when no longer needed.

## Technical references

- [FastAPI](https://fastapi.tiangolo.com/)
- [Ollama API](https://github.com/ollama/ollama/blob/main/docs/api.md)
- [Whisper source and installation](https://github.com/openai/whisper)
