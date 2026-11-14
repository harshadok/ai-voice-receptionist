import json
import os
import secrets
import threading
import time
import uuid
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .business import BookingRequest, Business, HTTPBusiness, business_router
from .runtime import LocalLLM, ProviderError, Store, now
from .speech import SpeechTools


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: Literal['answer_question', 'list_availability', 'propose_booking', 'cancel_pending']
    day: Optional[str] = None
    slot: Optional[str] = None
    name: Optional[str] = Field(default=None, max_length=100)
    contact: Optional[str] = Field(default=None, max_length=200)
    reply: str = Field(default='', max_length=1000)


class Turn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    speak: bool = False


class Confirmation(BaseModel):
    confirmation_token: str = Field(min_length=10, max_length=100)
    idempotency_key: str = Field(min_length=8, max_length=100)


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


def create_app(database=None, llm=None, speech=None, business=None):
    app = FastAPI(title='AI Voice Receptionist', version='1.0.0', description='English voice/text receptionist with structured tool dispatch, demo booking API, and explicit confirmation. Single-user local app; no telephone integration.')
    store = Store(database or os.environ.get('DATABASE_PATH', 'data/receptionist.sqlite3'))
    local_business = Business(store, os.environ.get('BUSINESS_TIMEZONE', 'Asia/Kolkata'))
    tools = business or (HTTPBusiness(os.environ['BUSINESS_API_URL']) if os.environ.get('BUSINESS_API_URL') else local_business)
    model, audio = llm or LocalLLM(), speech or SpeechTools()
    lock = threading.RLock()
    audio_dir = store.path.parent / 'audio'
    audio_dir.mkdir(exist_ok=True)
    app.include_router(business_router(local_business))

    def session(record_id):
        record = store.get('session', record_id)
        if record is None:
            raise HTTPException(404, 'Session not found.')
        return record

    def speak(text):
        artifact = str(uuid.uuid4())
        path = audio_dir / (artifact + '.wav')
        path.write_bytes(audio.synthesize(text))
        store.put('audio', {'file': path.name, 'created_at': now()}, artifact)
        return '/audio/' + artifact

    @app.get('/', include_in_schema=False)
    def index():
        from fastapi.responses import RedirectResponse
        return RedirectResponse('/docs')

    @app.get('/health')
    def health():
        return {'status': 'ready', 'speech_language': 'en', 'llm_model': getattr(model, 'model', 'injected'),
                'business_mode': 'http' if isinstance(tools, HTTPBusiness) else 'built_in_demo'}

    @app.post('/sessions', status_code=201)
    def start():
        record = {'created_at': now(), 'turns': [], 'pending': None, 'confirmations': {}}
        record_id = store.put('session', record)
        return dict(record, id=record_id)

    @app.get('/sessions/{record_id}')
    def get_session(record_id: str):
        return dict(session(record_id), id=record_id)

    def process(record_id, body):
        with lock:
            record = session(record_id)
            if len(record['turns']) >= 50:
                raise HTTPException(422, 'Start a new session after 50 turns.')
            try:
                raw = model.select_tool(
                    'You are the receptionist for Northwind Studio. Business facts: consulting appointments, Monday–Friday, Asia/Kolkata timezone, '
                    'slots at 09:00,10:00,11:00,14:00,15:00. For opening hours answer with these facts. '
                    'Use list_availability only to look up available slots. When a user supplies an exact slot, name and contact and requests a proposal, '
                    'call propose_booking with those exact values. Never invent availability or claim a booking is confirmed. '
                    'Only an explicit separate server confirmation can create a booking. Handle the latest message; history is context. '
                    'Current time: ' + now(), body.text, record['turns'])
                call = ToolCall.model_validate(raw)
                result = {'tool': call.tool}
                if call.tool == 'list_availability':
                    result['slots'] = tools.slots(call.day)
                    reply = 'Available appointment slots: ' + ', '.join(result['slots']) if result['slots'] else 'No slots are available for that day.'
                elif call.tool == 'propose_booking':
                    if not all([call.slot, call.name, call.contact]):
                        raise ValueError('A slot, name and contact are required for a proposal.')
                    from datetime import datetime
                    if call.slot not in tools.slots(datetime.fromisoformat(call.slot).date().isoformat()):
                        raise ValueError('Requested slot is not available. Check availability again.')
                    pending = {'slot': call.slot, 'name': call.name, 'contact': call.contact,
                               'token': secrets.token_urlsafe(24), 'expires_at': time.time() + 600}
                    record['pending'] = pending
                    result['pending'] = pending
                    reply = f"Please review and confirm the appointment for {call.name} at {call.slot}. It is not booked yet."
                elif call.tool == 'cancel_pending':
                    record['pending'] = None
                    reply = 'The pending proposal has been removed. No confirmed appointment was cancelled.'
                else:
                    reply = call.reply or 'Please provide your question or ask for appointment availability.'
            except (ProviderError, ValidationError) as exc:
                raise HTTPException(502, 'Model tool selection failed. Check the local model and retry.') from exc
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            record['turns'].append({'input': body.text, 'reply': reply, 'tool_result': result, 'at': now()})
            store.put('session', record, record_id)
            response = {'session_id': record_id, 'reply': reply, **result}
            if body.speak:
                try:
                    response['speech_url'] = speak(reply)
                except ProviderError as exc:
                    response['speech_error'] = str(exc)
            return response

    @app.post('/sessions/{record_id}/turns')
    def turn(record_id: str, body: Turn):
        return process(record_id, body)

    @app.post('/sessions/{record_id}/audio')
    async def audio_turn(record_id: str, file: UploadFile = File(...), speak_reply: bool = True):
        from starlette.concurrency import run_in_threadpool
        session(record_id)
        content = await file.read(10 * 1024 * 1024 + 1)
        await file.close()
        if not content or len(content) > 10 * 1024 * 1024:
            raise HTTPException(422, 'Upload a nonempty WAV file of at most 10 MB.')
        try:
            transcript = await run_in_threadpool(audio.transcribe, content)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except ProviderError as exc:
            raise HTTPException(503, str(exc)) from exc
        response = await run_in_threadpool(process, record_id, Turn(text=transcript, speak=speak_reply))
        return dict(response, transcript=transcript)

    @app.post('/sessions/{record_id}/confirm')
    def confirm(record_id: str, body: Confirmation):
        with lock:
            record = session(record_id)
            old = record['confirmations'].get(body.idempotency_key)
            if old:
                if old['token'] != body.confirmation_token:
                    raise HTTPException(409, 'Idempotency key already used with a different proposal.')
                return old['booking']
            pending = record['pending']
            if not pending or not secrets.compare_digest(pending['token'], body.confirmation_token) or pending['expires_at'] < time.time():
                raise HTTPException(409, 'Proposal expired or token does not match. Request a new proposal.')
            request = BookingRequest(slot=pending['slot'], name=pending['name'], contact=pending['contact'], session_id=record_id, idempotency_key=body.idempotency_key)
            try:
                booking = tools.book(request)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
            except ProviderError as exc:
                raise HTTPException(502, str(exc)) from exc
            record['confirmations'][body.idempotency_key] = {'token': body.confirmation_token, 'booking': booking}
            record['pending'] = None
            store.put('session', record, record_id)
            return booking

    @app.post('/speech')
    def speech_response(body: SpeechRequest):
        try:
            return Response(audio.synthesize(body.text), media_type='audio/wav')
        except ProviderError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.get('/audio/{artifact}')
    def get_audio(artifact: str):
        saved = store.get('audio', artifact)
        if saved is None:
            raise HTTPException(404, 'Audio not found.')
        path = audio_dir / saved['file']
        if not path.is_file():
            raise HTTPException(404, 'Audio file no longer exists.')
        return FileResponse(path, media_type='audio/wav')

    return app


app = create_app()
