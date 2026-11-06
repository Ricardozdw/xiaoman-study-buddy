"""上线检查的故障回归：启动瞬断、超时、缺图和登录失败不能误报通过。"""
import argparse
import io
import json
from http.client import RemoteDisconnected
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

from deploy.xiaoman.smoke_http import SmokeFailure, positive_seconds, run_smoke, wait_for_health


class HealthResponse(io.BytesIO):
    status = 200


class SequenceOpener:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.timeouts = []

    def open(self, url, timeout):
        self.timeouts.append(timeout)
        item = next(self.responses)
        if isinstance(item, Exception):
            raise item
        return HealthResponse(item)


@pytest.fixture
def clock(monkeypatch):
    from deploy.xiaoman import smoke_http

    now = [0.0]
    sleeps = []

    def advance(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(smoke_http, "time", SimpleNamespace(monotonic=lambda: now[0], sleep=advance))
    return now, sleeps


def test_startup_recovers_from_reset_disconnect_and_gateway_warmup(clock):
    opener = SequenceOpener([
        ConnectionResetError(), RemoteDisconnected(), URLError("not yet listening"),
        *(HTTPError("http://test/health", status, "warming up", {}, None) for status in (502, 503, 504)),
        b'{"ok":true}',
    ])
    wait_for_health(opener, "http://test", timeout=10)
    assert len(opener.timeouts) == 7
    assert clock[0][0] == 6


def test_startup_has_one_deadline_including_final_short_wait(clock):
    opener = SequenceOpener([ConnectionRefusedError()] * 3)
    with pytest.raises(SmokeFailure, match="2.5 秒内未就绪.*3 次请求"):
        wait_for_health(opener, "http://test", timeout=2.5)
    assert clock[0][0] == 2.5
    assert opener.timeouts == [2, 1.5, 0.5]


@pytest.mark.parametrize("status", [401, 403, 404, 500])
def test_startup_rejects_terminal_http_errors_without_retry(status, clock):
    opener = SequenceOpener([HTTPError("http://test/health", status, "private body", {}, None)])
    with pytest.raises(SmokeFailure, match=f"HTTP {status}，停止等待"):
        wait_for_health(opener, "http://test")
    assert len(opener.timeouts) == 1
    assert clock[1] == []


@pytest.mark.parametrize("body", [b"<html>login</html>", b'{"ok":false}', b'{"ok":1}', b"[]"])
def test_status_200_alone_does_not_mean_health_ready(body, clock):
    with pytest.raises(SmokeFailure, match="health:"):
        wait_for_health(SequenceOpener([body]), "http://test")
    assert clock[1] == []


@pytest.mark.parametrize("value", ["nan", "inf", "0", "-1"])
def test_startup_timeout_must_be_finite_and_positive(value):
    with pytest.raises(argparse.ArgumentTypeError):
        positive_seconds(value)


@pytest.fixture
def smoke_server():
    page = b'<script src="/study/assets/app.js"></script><link href="/study/assets/app.css">'
    state = {"overrides": {}, "counts": {}, "anonymous_allowed": False}
    resources = {
        "/health": (200, "application/json", b'{"ok":true}'),
        "/study/": (200, "text/html", page),
        "/study/assets/app.js": (200, "application/javascript", b"console.log('public fixture')"),
        "/study/assets/app.css": (200, "text/css", b"body {color: black}"),
        "/study/xiaoman-lake-blue.png": (200, "image/png", b"\x89PNG\r\n\x1a\npublic fixture"),
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            state["counts"][self.path] = state["counts"].get(self.path, 0) + 1
            if self.path == "/api/dashboard":
                if state["anonymous_allowed"] or self.headers.get("Cookie") == "smoke=fixture-session":
                    result = (200, "application/json", json.dumps({"ok": True, "data": {"range": "week"}}).encode())
                    result = state["overrides"].get(self.path, result)
                else:
                    result = (401, "application/json", b'{"ok":false}')
            else:
                result = state["overrides"].get(self.path, resources.get(self.path, (404, "text/plain", b"missing")))
            status, content_type, body = result
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != "/api/session":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Set-Cookie", "smoke=fixture-session; Path=/; HttpOnly")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_http_smoke_checks_assets_and_uses_fresh_cookie_session(smoke_server, capsys):
    base, state = smoke_server
    run_smoke(base)
    assert state["counts"]["/study/xiaoman-lake-blue.png"] == 1
    assert state["counts"]["/api/dashboard"] == 2
    assert "PASS: signed session and dashboard" in capsys.readouterr().out


@pytest.mark.parametrize("path,status,content_type,body,expected", [
    ("/study/xiaoman-lake-blue.png", 404, "text/html", b"private-response", "xiaoman-lake-blue.png: HTTP 404"),
    ("/study/xiaoman-lake-blue.png", 200, "image/png", b"private-response", "不是有效 PNG"),
    ("/study/assets/app.js", 200, "text/html", b"private-response", "资源类型不符"),
    ("/study/assets/app.css", 200, "text/css", b"", "文件为空"),
    ("/api/dashboard", 500, "application/json", b"private-response", "/api/dashboard: HTTP 500"),
    ("/api/dashboard", 200, "application/json", b'{"ok":true,"data":null}', "数据不符合约定"),
    ("/api/dashboard", 200, "application/json", b"private-response", "不是有效 JSON"),
])
def test_application_failures_are_not_retried_or_reported_as_success(smoke_server, path, status, content_type, body, expected):
    base, state = smoke_server
    state["overrides"][path] = status, content_type, body
    with pytest.raises(SmokeFailure) as error:
        run_smoke(base)
    assert expected in str(error.value)
    assert "private-response" not in str(error.value)
    assert state["counts"][path] == (2 if path == "/api/dashboard" else 1)


def test_anonymous_access_is_a_failure(smoke_server):
    base, state = smoke_server
    state["anonymous_allowed"] = True
    with pytest.raises(SmokeFailure, match="无登录态也能读取看板"):
        run_smoke(base)
