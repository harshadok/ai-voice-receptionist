import io
import hashlib
import time
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import wave

import numpy as np
import httpx

from .runtime import ProviderError


class SpeechTools:
    def __init__(self):
        self.model = None
        self.lock = threading.Lock()

    def transcribe(self, content):
        try:
            with wave.open(io.BytesIO(content)) as audio:
                channels, rate, width = audio.getnchannels(), audio.getframerate(), audio.getsampwidth()
                frames = audio.getnframes()
                if channels not in {1, 2} or width != 2 or not 8000 <= rate <= 48000 or not 0 < frames / rate <= 60:
                    raise ValueError('Use a 16-bit PCM WAV, mono/stereo, 8–48 kHz, up to 60 seconds.')
                samples = np.frombuffer(audio.readframes(frames), dtype='<i2').astype(np.float32) / 32768
                if len(samples) != frames * channels:
                    raise ValueError('Audio data is truncated.')
                samples = samples.reshape(-1, channels).mean(axis=1)
        except (wave.Error, EOFError) as exc:
            raise ValueError('Upload a valid 16-bit PCM WAV file.') from exc
        if np.max(np.abs(samples)) < 0.001:
            raise ValueError('Audio is silent; please record a spoken request.')
        if rate != 16000:
            samples = np.interp(np.arange(int(len(samples) * 16000 / rate)) / 16000, np.arange(len(samples)) / rate, samples).astype(np.float32)
        with self.lock:
            try:
                import whisper
                if self.model is None:
                    name = os.environ.get('WHISPER_MODEL', 'tiny.en')
                    if name not in whisper._MODELS:
                        raise ProviderError('Use a recognised Whisper model name, such as tiny.en or base.en.')
                    url = whisper._MODELS[name]
                    expected_sha = url.split('/')[-2]
                    directory = Path('data/models')
                    directory.mkdir(parents=True, exist_ok=True)
                    target = directory / (name + '.pt')
                    if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != expected_sha:
                        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as download:
                            temporary = Path(download.name)
                            try:
                                started = time.monotonic()
                                with httpx.stream('GET', url, timeout=30, follow_redirects=True) as response:
                                    response.raise_for_status()
                                    total = 0
                                    for chunk in response.iter_bytes():
                                        total += len(chunk)
                                        if total > 2 * 1024**3 or time.monotonic() - started > 600:
                                            raise ProviderError('Model download exceeded the size/time budget.')
                                        download.write(chunk)
                                download.flush()
                                if hashlib.sha256(temporary.read_bytes()).hexdigest() != expected_sha:
                                    raise ProviderError('Downloaded model failed its SHA-256 check.')
                                temporary.replace(target)
                            except (httpx.HTTPError, OSError) as exc:
                                raise ProviderError('Whisper model download failed. Retry with a working connection.') from exc
                            finally:
                                temporary.unlink(missing_ok=True)
                    self.model = whisper.load_model(name, device='cpu', download_root=str(directory))
                result = self.model.transcribe(samples, fp16=False, language='en', temperature=0)
                text = result['text'].strip()
            except (ImportError, RuntimeError, OSError) as exc:
                raise ProviderError('Whisper transcription failed; install requirements and download the configured model.') from exc
        if not text:
            raise ValueError('No speech was recognised.')
        return text

    def synthesize(self, text):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'reply.wav'
            input_file = Path(directory) / 'reply.txt'
            input_file.write_text(text)
            if shutil.which('say'):
                command = ['say', '-f', str(input_file), '-o', str(output), '--file-format=WAVE', '--data-format=LEI16@16000']
            elif shutil.which('espeak-ng'):
                command = ['espeak-ng', '-f', str(input_file), '-w', str(output)]
            else:
                raise ProviderError('Install a system TTS engine: macOS say or Linux espeak-ng.')
            try:
                subprocess.run(command, check=True, capture_output=True, timeout=60)
                return output.read_bytes()
            except (subprocess.SubprocessError, OSError) as exc:
                raise ProviderError('Text-to-speech failed.') from exc
