import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx


class ProviderError(RuntimeError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(str(self.path), timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def put(self, kind, payload, record_id=None):
        record_id = record_id or str(uuid.uuid4())
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO records VALUES (?, ?, ?)", (record_id, kind, json.dumps(payload)))
        return record_id

    def get(self, kind, record_id):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM records WHERE kind=? AND id=?", (kind, record_id)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, kind):
        with self.connect() as db:
            rows = db.execute("SELECT id, payload FROM records WHERE kind=? ORDER BY rowid DESC LIMIT 100", (kind,)).fetchall()
        return [dict(json.loads(row["payload"]), id=row["id"]) for row in rows]


class LocalLLM:
    def __init__(self, base_url=None, model=None):
        self.base_url = (base_url or os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.model = model or os.environ.get("AI_MODEL", "qwen2.5:1.5b")

    def complete(self, messages, schema=None, max_tokens=512):
        payload = {"model": self.model, "messages": messages, "stream": False,
                   "options": {"temperature": 0, "num_predict": max_tokens, "num_ctx": 8192}}
        if schema is not None:
            payload["format"] = schema
        try:
            response = httpx.post(self.base_url + "/api/chat", json=payload, timeout=180)
            response.raise_for_status()
            raw = response.json()
            text = raw["message"]["content"]
            if not isinstance(text, str):
                raise ValueError("Expected textual model output")
            return {"text": text, "input_tokens": raw.get("prompt_eval_count"), "output_tokens": raw.get("eval_count")}
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise ProviderError("Local model unavailable or returned invalid output. Start Ollama and pull the configured AI_MODEL.") from exc

    def structured(self, system, data, schema):
        result = self.complete([{"role": "system", "content": system},
                                {"role": "user", "content": json.dumps(data)}], schema=schema)
        try:
            value = json.loads(result["text"])
            if not isinstance(value, dict):
                raise ValueError("Expected a JSON object")
            return value
        except ValueError as exc:
            raise ProviderError("Model returned malformed structured output.") from exc

    def select_tool(self, system, message, history):
        def tool(name, description, properties, required):
            return {'type':'function','function':{'name':name,'description':description,'parameters':{'type':'object','properties':properties,'required':required,'additionalProperties':False}}}
        text = {'type':'string'}
        tools = [
            tool('answer_question','Answer a general question using the provided business facts. Opening-hours questions belong here.',{'reply':text},['reply']),
            tool('list_availability','Look up appointment availability for a requested date. This only lists slots.',{'day':{'type':'string','description':'ISO YYYY-MM-DD date, or omit for the next day.'}},[]),
            tool('propose_booking','Propose a booking when the user gives a slot, name and contact. Does not book until explicit confirmation.',{'slot':{'type':'string','description':'Exact ISO timestamp with offset supplied by the user.'},'name':text,'contact':text},['slot','name','contact']),
            tool('cancel_pending','Remove a pending booking proposal, not a confirmed booking.',{},[]),
        ]
        messages = [{'role':'system','content':system}]
        for turn in history[-3:]:
            messages.extend([{'role':'user','content':turn['input']},{'role':'assistant','content':turn['reply']}])
        messages.append({'role':'user','content':message})
        try:
            response = httpx.post(self.base_url+'/api/chat',json={'model':self.model,'stream':False,'messages':messages,'tools':tools,'options':{'temperature':0,'num_predict':400,'num_ctx':4096}},timeout=180)
            response.raise_for_status()
            result = response.json()['message']
            calls = result.get('tool_calls') or []
            if not calls:
                if not result.get('content','').strip():
                    raise ValueError('No answer or tool call returned.')
                return {'tool':'answer_question','reply':result['content'][:1000]}
            if len(calls)!=1:
                raise ValueError('Only one tool call per turn is allowed.')
            function = calls[0]['function']
            arguments = function['arguments']
            if not isinstance(arguments,dict):
                raise ValueError('Tool arguments must be an object.')
            return dict(arguments,tool=function['name'])
        except (httpx.HTTPError,ValueError,KeyError,TypeError) as exc:
            raise ProviderError('Native tool selection failed.') from exc
