#!/usr/bin/env python3
"""A small voice server for Postcrew: Kokoro (Apache-2.0, runs on a CPU) behind an OpenAI-style /v1/audio/speech endpoint.

  pip install kokoro-onnx soundfile   (and ffmpeg on the PATH)
  files: kokoro-v1.0.onnx and voices-v1.0.bin from https://github.com/thewh1teagle/kokoro-onnx/releases (model-files-v1.0)
  python3 scripts/kokoro_server.py --models ~/kokoro --port 8880

Then in the workspace config: video.voice = {"provider": "openai-compatible", "base_url": "http://localhost:8880/v1",
"model": "kokoro", "voice_id": "af_heart", "speed": 0.95}. Voices: af_heart af_bella af_nicole am_michael am_adam bf_emma bm_george...
"""
import argparse
import io
import json
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=str(Path.home() / "kokoro"))
    ap.add_argument("--port", type=int, default=8880)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    import soundfile as sf
    from kokoro_onnx import Kokoro
    root = Path(a.models).expanduser()
    tts, lock = Kokoro(str(root / "kokoro-v1.0.onnx"), str(root / "voices-v1.0.bin")), Lock()

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body, kind="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self._send(200, json.dumps({"ok": True, "voices": sorted(tts.get_voices())}).encode())

        def do_POST(self):
            try:
                req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                text = str(req.get("input") or "").strip()
                if not text:
                    return self._send(400, b'{"error": "no input"}')
                voice = req.get("voice") or "af_heart"
                if voice not in tts.get_voices():
                    voice = "af_heart"
                with lock:   # one at a time: the model is not thread safe
                    samples, rate = tts.create(text, voice=voice, speed=float(req.get("speed") or 1.0), lang="en-us")
                wav = io.BytesIO()
                sf.write(wav, samples, rate, format="WAV")
                mp3 = subprocess.run(["ffmpeg", "-v", "error", "-f", "wav", "-i", "-", "-f", "mp3", "-b:a", "128k", "-"],
                                     input=wav.getvalue(), capture_output=True, check=True).stdout
                self._send(200, mp3, "audio/mpeg")
            except Exception as e:   # noqa: BLE001 (a server must answer, whatever happened)
                self._send(500, json.dumps({"error": str(e)}).encode())

        def log_message(self, *args):
            pass

    print(f"Kokoro voice server on http://{a.host}:{a.port}/v1", flush=True)
    ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
