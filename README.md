# AI Voice Receptionist

**Status: Planning / documentation only.** This repository currently contains a project specification and implementation roadmap. No working application, provider integration, deployment, or measured results are included yet.

A personal learning project by [Harshad Odakkal](https://github.com/harshadok), building on professional Flutter and mobile engineering experience while transitioning toward AI/mobile engineering.

## Problem and goal

Create a voice interface that answers routine enquiries and helps users request appointments through controlled API tools.

## Skills to practise

- Speech-to-text
- Text-to-speech
- Tool calling
- API integration
- Voice conversation state

## Planned end-to-end workflow

1. Capture an audio turn with an explicit recording control.
2. Transcribe speech and retain the current conversation state.
3. Interpret the request and select an allowlisted tool when necessary.
4. Validate arguments and fetch information from a mock business API.
5. Ask for explicit confirmation before creating or changing an appointment.
6. Generate a response and play synthesized speech; offer a text fallback on failure.

## Proposed architecture

Flutter microphone and playback client; Python API service; speech and LLM provider adapters; mock appointment API.

The stack is a design proposal. Specific providers, libraries, model versions, and database products will be selected and documented during implementation.

## Planned API surface

- `POST /sessions` — create a conversation
- `POST /sessions/{id}/turns` — submit an audio or text turn
- `GET /availability` — read mock appointment slots
- `POST /appointments` — create a confirmed mock booking with an idempotency key

These endpoints are proposed contracts; they are not implemented.

## Core data model

Session(id, status, turns); ToolCall(name, arguments, result); Appointment(id, slot, contact, confirmation_state).

## Flutter/mobile experience

Push-to-talk interaction, live transcript, playback controls, booking confirmation, and a visible text fallback.

## Evaluation and acceptance plan

- [ ] Evaluate transcription on a fixed set of synthetic or consented audio samples.
- [ ] Test tool argument validation, tool allowlists, timeouts, and failed API calls.
- [ ] Ensure bookings require confirmation and retries cannot create duplicate bookings.
- [ ] Measure transcription, model, tool, and speech latency separately.
- [ ] Test interruptions, ambiguous dates, and unavailable appointment slots.

No accuracy, latency, cost, or reliability results have been measured. Results will be added only after reproducible runs.

## Implementation roadmap

- [ ] **Milestone 1:** Create a text-only conversation connected to a mock availability API.
- [ ] **Milestone 2:** Add validated tool calling and confirmation before booking.
- [ ] **Milestone 3:** Connect speech-to-text and text-to-speech adapters.
- [ ] **Milestone 4:** Build Flutter audio capture, playback, and transcript screens.
- [ ] **Milestone 5:** Record a synthetic booking demonstration and document latency and error results.

## Planned demonstration

Ask for availability, select a slot, confirm the booking, and replay the same request to demonstrate duplicate prevention.

## Data and operational boundaries

Use mock bookings and synthetic contact details initially. Make recording visible, avoid retaining raw audio by default, and offer escalation when a request cannot be resolved.

## Getting started today

1. Read the proposed workflow and choose the first milestone.
2. Decide on providers and local development tools; record those decisions before implementation.
3. Add application code and a reproducible setup guide as the first milestone is built.
4. Use synthetic or public test data and keep credentials outside version control.

**There is no runnable quick start yet.** Installation and run commands will be added when code exists.

## Suggested future layout

```text
apps/mobile/        # Planned Flutter client
services/api/       # Planned application API
evals/              # Planned fixtures and evaluation runs
docs/               # Architecture decisions and demonstration notes
```

These directories describe the intended structure and have not been implemented.

## Portfolio context

This is an independent planned portfolio project, not client work or a production deployment. Its current scope is documentation; update the status and roadmap as working milestones are completed.
