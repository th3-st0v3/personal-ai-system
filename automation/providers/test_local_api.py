from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

from .local_api import LocalProviderAPI
from .protocol import ProviderResponse


class FakeProvider:
    name = "fake"

    def health(self):
        return {"available": True, "provider": self.name}

    def generate(self, messages, *, model=None):
        return ProviderResponse(self.name, model or "fake-model", "hello from provider", 1.0)


def test_local_api_health_and_completion():
    server = ThreadingHTTPServer(("127.0.0.1", 0), LocalProviderAPI)
    server.provider = FakeProvider()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        conn.request("GET", "/health")
        response = conn.getresponse()
        assert response.status == 200
        assert json.loads(response.read())["available"] is True

        body = json.dumps({"model": "fake-model", "messages": [{"role": "user", "content": "hello"}]}).encode()
        conn.request("POST", "/v1/chat/completions", body=body, headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        payload = json.loads(response.read())
        assert response.status == 200
        assert payload["choices"][0]["message"]["content"] == "hello from provider"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
