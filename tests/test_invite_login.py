"""邀请码登录：配置了 INVITE_CODES 时，没有邀请码进不来；一个码就是一个账号，可重复使用。"""
from __future__ import annotations

import pytest

from app import invite
from app.auth import mint_user_token
from app.main import app
from tests.conftest import RawTestClient

CODES = "XM-AAAA-BBBB:试用1,XM-CCCC-DDDD:试用2"


@pytest.fixture
def raw():
    return RawTestClient(app)


@pytest.fixture
def invite_on(monkeypatch):
    monkeypatch.setenv("INVITE_CODES", CODES)
    invite._fails.clear()
    yield
    invite._fails.clear()


def test_without_codes_behaviour_is_unchanged(raw, monkeypatch):
    monkeypatch.delenv("INVITE_CODES", raising=False)
    r = raw.post("/api/session")
    assert r.status_code == 200 and r.json()["data"]["user_id"].startswith("u_")
    assert raw.post("/api/session/invite", json={"code": "x"}).status_code == 400


def test_no_code_no_session(raw, invite_on):
    r = raw.post("/api/session")
    assert r.status_code == 401 and r.json()["detail"]["code"] == "invite_required"
    assert "ja_session" not in r.cookies
    assert raw.get("/api/plan/today").status_code == 401


def test_valid_code_logs_in_and_same_code_is_same_account(raw, invite_on):
    r = raw.post("/api/session/invite", json={"code": "xm-aaaa bbbb"})  # 大小写 / 空格 / 横线不敏感
    assert r.status_code == 200 and r.json()["data"]["label"] == "试用1"
    uid = r.json()["data"]["user_id"]
    assert uid.startswith("u_inv_")
    assert raw.post("/api/session").json()["data"]["user_id"] == uid  # 之后刷新页面保持登录
    assert raw.get("/api/plan/today").status_code == 200
    other_device = RawTestClient(app)
    assert other_device.post("/api/session/invite", json={"code": "XM-AAAA-BBBB"}).json()["data"]["user_id"] == uid
    assert other_device.post("/api/session/invite", json={"code": "XM-CCCC-DDDD"}).json()["data"]["user_id"] != uid


def test_wrong_code_rejected_and_rate_limited(raw, invite_on):
    for _ in range(10):
        assert raw.post("/api/session/invite", json={"code": "XM-WRONG-0000"}).status_code == 401
    r = raw.post("/api/session/invite", json={"code": "XM-AAAA-BBBB"})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "too_many_attempts"


def test_old_anonymous_sessions_stop_working(raw, invite_on):
    headers = {"X-User-Token": mint_user_token("u_anonymous123")}
    assert raw.get("/api/plan/today", headers=headers).status_code == 401
    assert raw.post("/api/session", headers=headers).status_code == 401


def test_logout_clears_session(raw, invite_on):
    raw.post("/api/session/invite", json={"code": "XM-AAAA-BBBB"})
    assert raw.post("/api/session").status_code == 200
    raw.post("/api/session/logout")
    raw.cookies.clear()
    assert raw.post("/api/session").status_code == 401


def test_codes_are_not_echoed_in_responses(raw, invite_on):
    r = raw.post("/api/session/invite", json={"code": "XM-AAAA-BBBB"})
    assert "AAAA" not in r.text and "BBBB" not in r.text
