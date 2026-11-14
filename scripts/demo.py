"""Run a synthetic-data walkthrough against a running local API."""
import argparse
import json
from pathlib import Path
import httpx

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--url', default='http://127.0.0.1:8101')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
client = httpx.Client(base_url=args.url, timeout=300)

def call(method, path, **kwargs):
    response = client.request(method, path, **kwargs)
    response.raise_for_status()
    return response.json()

session = call('POST','/sessions')['id']
reply = call('POST','/sessions/'+session+'/turns',json={'text':'What are your opening hours?','speak':True})
print(json.dumps(reply,indent=2))
if reply.get('speech_url'):
    response=client.get(reply['speech_url']); response.raise_for_status()
    target=root/'data/demo-reply.wav'; target.parent.mkdir(exist_ok=True); target.write_bytes(response.content)
    print('Saved reply audio:',target)
print('No booking was created. Use /business/availability, propose a booking, then explicitly POST /sessions/{id}/confirm with its token and a stable idempotency key.')
