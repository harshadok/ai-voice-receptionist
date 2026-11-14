# Verification — 14 November 2026

## Automated checks

- Python backend suite: **5 passed** in the local development environment.
- `python -m pip check`: no broken requirements for the installed project environment.
- Deterministic tests isolate provider failures using doubles; the real-provider checks below are separate evidence.
- GitHub Actions runs the backend suite on Python 3.11 without requiring model weights or credentials.

## Real-provider checks

- Real macOS text-to-speech generated a 16 kHz PCM WAV from a synthetic opening-hours enquiry.
- Real Whisper tiny.en transcribed the generated audio: “Hello, I would like to know your opening hours.”
- Real Ollama Qwen2.5 1.5B native function calling answered the enquiry and proposed a supplied valid appointment slot.
- Explicit confirmation created a synthetic local booking; retrying the same idempotency key returned the same booking ID.
- The HTTP business adapter also created a synthetic booking against a live local business API and returned the same booking on retry.
- The reply WAV was retrieved successfully. No telephone call, email, SMS, or external customer booking was performed.

## Scope

This is a runnable single-user local portfolio implementation. Smoke checks on synthetic/public data are not a production-readiness claim, a general quality benchmark, or proof that an AI output is always correct. See README for supported formats, runtime dependencies and operational boundaries.
