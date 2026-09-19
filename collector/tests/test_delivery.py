"""Outbox and transport against a real local HTTP server."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from flockit import config, outbox, transport


class _Server:
    def __init__(self):
        self.received = []
        self.status = 200
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                parent.received.append((self.headers.get("Authorization"), body))
                self.send_response(parent.status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()


@pytest.fixture
def server():
    s = _Server()
    yield s
    s.close()


def _event(i):
    return {"event_id": "e%d" % i, "type": "session.activity", "session": {"external_id": "s"}}


def test_flush_sends_and_clears(server):
    cfg = config.Config(server_url=server.url, token="flk_abc")
    for i in range(3):
        outbox.append(_event(i))
    assert transport.flush(cfg) == 3
    assert outbox.pending() == 0
    auth, body = server.received[0]
    assert auth == "Bearer flk_abc"
    assert [e["event_id"] for e in body["events"]] == ["e0", "e1", "e2"]


def test_server_down_keeps_events():
    cfg = config.Config(server_url="http://127.0.0.1:9", token="flk_abc")
    outbox.append(_event(1))
    assert transport.flush(cfg) == 0
    assert outbox.pending() == 1


def test_server_error_keeps_events_in_order(server):
    cfg = config.Config(server_url=server.url, token="t")
    server.status = 503
    for i in range(3):
        outbox.append(_event(i))
    transport.flush(cfg)
    outbox.append(_event(3))
    server.status = 200
    transport.flush(cfg)
    sent = [e["event_id"] for e in server.received[-1][1]["events"]]
    assert sent == ["e0", "e1", "e2", "e3"]


def test_rejected_batch_is_dropped_not_retried_forever(server):
    cfg = config.Config(server_url=server.url, token="t")
    server.status = 422
    outbox.append(_event(1))
    transport.flush(cfg)
    assert outbox.pending() == 0


def test_large_backlog_is_batched(server):
    cfg = config.Config(server_url=server.url, token="t")
    for i in range(450):
        outbox.append(_event(i))
    assert transport.flush(cfg) == 450
    assert [len(b["events"]) for _, b in server.received] == [200, 200, 50]


def test_outbox_is_bounded():
    for i in range(outbox.MAX_EVENTS + 5):
        outbox.append(_event(i))
    outbox.remove(["e0"])  # any rewrite enforces the cap
    assert outbox.pending() == outbox.MAX_EVENTS
    assert outbox.snapshot()[-1]["event_id"] == "e%d" % (outbox.MAX_EVENTS + 4)


def test_events_survive_a_flush_killed_mid_send(server, monkeypatch):
    cfg = config.Config(server_url=server.url, token="t")
    for i in range(3):
        outbox.append(_event(i))

    def killed(*args, **kwargs):
        raise KeyboardInterrupt  # stands in for the process dying during the request

    monkeypatch.setattr(transport, "send", killed)
    with pytest.raises(KeyboardInterrupt):
        transport.flush(cfg)
    assert outbox.pending() == 3


def test_events_appended_during_a_flush_are_kept(server, monkeypatch):
    cfg = config.Config(server_url=server.url, token="t")
    outbox.append(_event(1))
    real_send = transport.send

    def send_and_append(c, batch):
        outbox.append(_event(2))  # another session's hook writes while we send
        return real_send(c, batch)

    monkeypatch.setattr(transport, "send", send_and_append)
    transport.flush(cfg)
    assert [e["event_id"] for e in outbox.snapshot()] == ["e2"]


def test_outbox_and_config_are_private(configured, flockit_home):
    outbox.append(_event(1))
    assert oct(config.config_path().stat().st_mode & 0o777) == "0o600"
    assert oct(config.outbox_path().stat().st_mode & 0o777) == "0o600"
