"""A tiny stand-in for the Flockit server, for agent and runner tests."""

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class StubServer:
    def __init__(self):
        self.tasks = []  # handed out once each by the poll endpoints
        self.offers = []
        self.events = []
        self.reports = []
        self.state = {}
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def _json(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                path = self.path.split("?")[0]
                if path in ("/api/agent/poll", "/api/runner/poll"):
                    task = parent.tasks.pop(0) if parent.tasks else None
                    offers, parent.offers = parent.offers, []
                    return self._json(200, {"machine_id": "m1", "task": task, "offers": offers})
                if path == "/api/ingest/events":
                    parent.events.extend(body.get("events", []))
                    return self._json(200, {"accepted": len(body.get("events", [])), "duplicates": 0, "rejected": 0})
                m = re.match(r"^/api/(agent|runner)/tasks/([^/]+)/status$", path)
                if m:
                    parent.reports.append((m.group(2), body))
                    parent.state[m.group(2)] = body["status"]
                    return self._json(200, {"status": body["status"]})
                return self._json(404, {"detail": "not found"})

            def do_GET(self):
                m = re.match(r"^/api/(?:agent|runner)/tasks/([^/]+)(?:/state)?$", self.path)
                if m:
                    return self._json(200, {"status": parent.state.get(m.group(1), "running")})
                return self._json(404, {"detail": "not found"})

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
