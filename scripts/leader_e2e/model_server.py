"""Local model HTTP test double; every call still passes through ModelClient."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class ModelServer:
    def __init__(self):
        self.calls: list[dict] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                owner.calls.append(data)
                messages = data.get("messages", [])
                content = messages[-1]["content"] if messages else ""
                if "[test-timeout]" in content:
                    time.sleep(2)
                result = {"model": "local-test-model", "choices": [{"message": {
                    "role": "assistant", "content": "Local model: " + content[:100]}}],
                    "usage": {"total_tokens": 20}}
                if "[test-malformed]" in content:
                    result = {"choices": []}
                encoded = json.dumps(result).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                try: self.wfile.write(encoded)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError): pass

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
