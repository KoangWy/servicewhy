"""Stand-in for a Meterless Nightshift Runtime (OpenAI-compatible), served by stdlib http.server in a thread.

It only emulates the NIGHTSHIFT RUNTIME CONTRACT the app relies on (Bearer auth, GET /v1/models, POST
/v1/chat/completions). It is a test double for the keyless suite. A real Nightshift was exercised separately
(2026-10-27); the evidence run is in logs/nightshift-example/.
"""
from __future__ import annotations

import json
import socket
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_sleep = time.sleep  # tests may patch time.sleep; the stub's own delay must stay real
TOKEN = "nightshift-runtime-token-0123456789"


class Stub:
    def __init__(self, *, models=("meta/llama-x",), token=TOKEN, reply="OK", delay=0.0, chat_status=200,
                 reject_temperature=False, routed_model=None):
        self.models = None if models is None else list(models)  # None: no /models endpoint
        self.token, self.reply, self.delay = token, reply, delay
        self.chat_status, self.reject_temperature = chat_status, reject_temperature
        self.routed_model = routed_model  # real Nightshift reports the answering model in meterless.routed_model
        self.requests: list[dict] = []
        self.url = ""

    def handler(self):
        stub = self

        class H(BaseHTTPRequestHandler):
            def _send(self, status: int, body: dict):
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _handle(self, method: str):
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length) or b"null") if length else None
                stub.requests.append({"method": method, "path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()},
                                      "json": payload})
                if stub.delay:
                    _sleep(stub.delay)
                if self.headers.get("Authorization") != f"Bearer {stub.token}":
                    return self._send(401, {"error": {"message": "invalid runtime token"}})
                if method == "GET" and self.path == "/v1/models" and stub.models is not None:
                    return self._send(200, {"object": "list", "data": [{"id": m, "object": "model"} for m in stub.models]})
                if method == "POST" and self.path == "/v1/chat/completions":
                    if stub.reject_temperature and "temperature" in payload:
                        return self._send(400, {"error": {"message": "Unsupported parameter: 'temperature'"}})
                    if stub.chat_status != 200:
                        return self._send(stub.chat_status, {"error": {"message": "no model connected"}})
                    body = {"model": payload["model"], "usage": {"total_tokens": 3},
                            "choices": [{"message": {"role": "assistant", "content": stub.reply}}]}
                    if stub.routed_model:
                        body["meterless"] = {"routed_model": stub.routed_model}
                    return self._send(200, body)
                self._send(404, {"error": {"message": "not found"}})

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

            def log_message(self, *a):
                pass

        return H


@contextmanager
def nightshift(**kw):
    stub = Stub(**kw)
    server = ThreadingHTTPServer(("127.0.0.1", 0), stub.handler())
    server.daemon_threads = True
    stub.url = f"http://127.0.0.1:{server.server_address[1]}/v1"
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        yield stub
    finally:
        server.shutdown()
        server.server_close()


def closed_port_url() -> str:
    """A loopback URL nothing listens on (connection refused)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{s.getsockname()[1]}/v1"
