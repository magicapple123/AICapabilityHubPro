"""Exercise the real HTTP reader against an isolated loopback fixture."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import smoke_check


def test_read_only_smoke_handles_gateway_http_errors(monkeypatch, capsys) -> None:
    seen: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            seen.append(self.path)
            if "internal/" in self.path:
                status, code = 403, 1001
            elif self.path.endswith("profile"):
                status, code = 401, 1001
            else:
                status, code = 200, 0
            body = json.dumps({"code": code, "message": "fixture", "data": {}, "requestId": "test"}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setattr("sys.argv", ["smoke_check.py", "--gateway", f"http://127.0.0.1:{server.server_port}"])
        assert smoke_check.main() == 0
        assert len(seen) == 8
        assert "8/8 passed" in capsys.readouterr().out
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
