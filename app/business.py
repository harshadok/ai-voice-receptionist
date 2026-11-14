import json
import sqlite3
import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .runtime import Store, ProviderError, now


class BookingRequest(BaseModel):
    slot: str
    name: str = Field(min_length=1, max_length=100)
    contact: str = Field(min_length=1, max_length=200)
    session_id: str
    idempotency_key: str = Field(min_length=8, max_length=100)


class Business:
    def __init__(self, store, timezone='Asia/Kolkata'):
        self.store = store
        self.timezone = ZoneInfo(timezone)
        with store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS bookings (id TEXT PRIMARY KEY, slot TEXT NOT NULL UNIQUE, request_key TEXT NOT NULL UNIQUE, payload TEXT NOT NULL)')

    def slots(self, day=None):
        current = datetime.now(self.timezone)
        selected = datetime.fromisoformat(day).date() if day else (current.date() + timedelta(days=1))
        if not current.date() <= selected <= current.date() + timedelta(days=30):
            raise ValueError('Choose a date between today and 30 days from today.')
        if selected.weekday() >= 5:
            return []
        with self.store.connect() as db:
            booked = {row[0] for row in db.execute('SELECT slot FROM bookings')}
        values = [datetime.combine(selected, time(hour), tzinfo=self.timezone) for hour in [9, 10, 11, 14, 15]]
        return [value.isoformat() for value in values if value > current and value.isoformat() not in booked]

    def book(self, request):
        key = request.session_id + ':' + request.idempotency_key
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT payload FROM bookings WHERE request_key=?', (key,)).fetchone()
            if existing:
                saved = json.loads(existing[0])
                if any(saved[field] != getattr(request, field) for field in ['slot', 'name', 'contact']):
                    raise ValueError('Idempotency key was already used for a different booking.')
                return saved
            try:
                day = datetime.fromisoformat(request.slot).astimezone(self.timezone).date().isoformat()
                if request.slot not in self.slots(day):
                    raise ValueError('This slot is unavailable. Request current availability.')
                record = dict(request.model_dump(), id=str(uuid.uuid4()), created_at=now(), status='confirmed')
                db.execute('INSERT INTO bookings VALUES (?,?,?,?)', (record['id'], request.slot, key, json.dumps(record)))
            except sqlite3.IntegrityError as exc:
                raise ValueError('This slot was booked by another session.') from exc
        return record


class HTTPBusiness:
    """Optional external business API adapter; URL is deployment configuration, never model input."""
    def __init__(self, url):
        self.url = url.rstrip('/')

    def slots(self, day=None):
        try:
            response = httpx.get(self.url + '/availability', params={'day': day} if day else {}, timeout=15)
            response.raise_for_status()
            return response.json()['slots']
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise ProviderError('Business availability API failed.') from exc

    def book(self, request):
        try:
            response = httpx.post(self.url + '/appointments', json=request.model_dump(), timeout=15)
            if response.status_code == 409:
                raise ValueError('Slot conflict or reused idempotency key.')
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise ProviderError('Business booking API failed. Retrying with the same key is safe.') from exc


def business_router(service):
    router = APIRouter(prefix='/business', tags=['Demo business API'])

    @router.get('/availability')
    def availability(day: str = None):
        try:
            return {'slots': service.slots(day), 'timezone': str(service.timezone)}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post('/appointments', status_code=201)
    def appointment(body: BookingRequest):
        try:
            return service.book(body)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    return router
