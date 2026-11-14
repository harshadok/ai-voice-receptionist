import io
import json
import time
import wave
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.business import BookingRequest, Business
from app.main import create_app
from app.runtime import Store
from app.speech import SpeechTools


class Model:
    def __init__(self):
        self.response = {'tool': 'answer_question', 'reply': 'How can I help?'}
    def select_tool(self, *args):
        return self.response


class Speech:
    def transcribe(self, content):
        return 'What are your opening hours?'
    def synthesize(self, text):
        return b'RIFFsynthetic-test-audio'


def next_weekday():
    day = datetime.now().date() + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day.isoformat()


@pytest.fixture
def setup(tmp_path):
    model = Model()
    client = TestClient(create_app(tmp_path / 'db', model, Speech()))
    session = client.post('/sessions').json()['id']
    return client, model, session


def propose(setup):
    client, model, session = setup
    slot = client.get('/business/availability', params={'day': next_weekday()}).json()['slots'][0]
    model.response = {'tool': 'propose_booking', 'slot': slot, 'name': 'Demo User', 'contact': 'demo@example.com'}
    response = client.post('/sessions/' + session + '/turns', json={'text': 'Please propose that slot.'})
    assert response.status_code == 200, response.text
    return response.json()['pending']


def test_explicit_confirmation_and_idempotency(setup):
    client, model, session = setup
    pending = propose(setup)
    assert pending['slot'] in client.get('/business/availability', params={'day': next_weekday()}).json()['slots']
    bad = client.post('/sessions/' + session + '/confirm', json={'confirmation_token': 'wrong-token-value', 'idempotency_key': 'booking-key-1'})
    assert bad.status_code == 409
    request = {'confirmation_token': pending['token'], 'idempotency_key': 'booking-key-1'}
    first = client.post('/sessions/' + session + '/confirm', json=request)
    assert first.status_code == 200, first.text
    second = client.post('/sessions/' + session + '/confirm', json=request)
    assert second.json()['id'] == first.json()['id']
    assert pending['slot'] not in client.get('/business/availability', params={'day': next_weekday()}).json()['slots']
    request['confirmation_token'] = 'different-valid-length-token'
    assert client.post('/sessions/' + session + '/confirm', json=request).status_code == 409


def test_unknown_tools_cannot_mutate_booking(setup):
    client, model, session = setup
    model.response = {'tool': 'confirm_booking', 'reply': 'Booked!'}
    assert client.post('/sessions/' + session + '/turns', json={'text': 'Book without confirmation'}).status_code == 502
    assert client.get('/sessions/' + session).json()['pending'] is None


def test_cancel_pending_and_audio_response(setup):
    client, model, session = setup
    propose(setup)
    model.response = {'tool': 'cancel_pending'}
    assert client.post('/sessions/' + session + '/turns', json={'text': 'Cancel the proposal'}).status_code == 200
    assert client.get('/sessions/' + session).json()['pending'] is None
    model.response = {'tool': 'answer_question', 'reply': 'Monday to Friday.'}
    response = client.post('/sessions/' + session + '/audio', files={'file': ('request.wav', b'test audio')})
    assert response.status_code == 200
    assert response.json()['transcript'] == 'What are your opening hours?'
    assert client.get(response.json()['speech_url']).content.startswith(b'RIFF')


def test_business_conflict_and_payload_bound_idempotency(tmp_path):
    service = Business(Store(tmp_path / 'db'))
    slot = service.slots(next_weekday())[0]
    request = BookingRequest(slot=slot, name='A', contact='a@example.com', session_id='a', idempotency_key='stable-key-1')
    first = service.book(request)
    assert service.book(request)['id'] == first['id']
    with pytest.raises(ValueError):
        service.book(request.model_copy(update={'name': 'Another user'}))
    with pytest.raises(ValueError):
        service.book(request.model_copy(update={'session_id': 'b'}))


def test_real_audio_validation_without_model_download():
    audio = SpeechTools()
    with pytest.raises(ValueError):
        audio.transcribe(b'not a WAV')
    output = io.BytesIO()
    with wave.open(output, 'wb') as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b'\0\0' * 16000)
    with pytest.raises(ValueError, match='silent'):
        audio.transcribe(output.getvalue())
