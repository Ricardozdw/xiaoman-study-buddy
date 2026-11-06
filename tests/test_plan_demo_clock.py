"""计划线演示开关：跳到明天 / 跳过几天 / 回到今天。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest


@pytest.fixture
def demo_on(monkeypatch):
    monkeypatch.setenv("XIAOMAN_DEMO_CLOCK", "1")


@pytest.fixture
def demo_off(monkeypatch):
    monkeypatch.delenv("XIAOMAN_DEMO_CLOCK", raising=False)


def _clock(client, headers):
    return client.get("/api/demo/clock", headers=headers).json()["data"]


def test_off_by_default_post_is_404_and_date_is_real(client, auth, demo_off):
    headers = auth("demo-off")
    view = _clock(client, headers)
    assert view["enabled"] is False and view["offset_days"] == 0
    assert view["today"] == view["real_today"]
    assert client.post("/api/demo/clock", json={"days": 1}, headers=headers).status_code == 404
    assert client.post("/api/demo/clock/reset", headers=headers).status_code == 404
    plan = client.get("/api/plan/today", headers=headers).json()["data"]
    assert plan["date"] == view["real_today"]


def test_leftover_offset_is_ignored_when_switch_is_off(client, auth, monkeypatch):
    headers = auth("demo-leftover")
    monkeypatch.setenv("XIAOMAN_DEMO_CLOCK", "1")
    client.post("/api/demo/clock", json={"days": 8}, headers=headers)
    monkeypatch.delenv("XIAOMAN_DEMO_CLOCK")
    view = _clock(client, headers)
    assert view["offset_days"] == 0
    assert client.get("/api/plan/today", headers=headers).json()["data"]["date"] == view["real_today"]


def test_jump_to_tomorrow_puts_mistakes_first(client, auth, demo_on):
    headers = auth("demo-tomorrow")
    day1 = client.get("/api/plan/today", headers=headers).json()["data"]
    client.post("/api/attempts", json={"question_id": "demo-tomorrow:q1", "answer": "A"}, headers=headers)
    for task in day1["tasks"]:
        client.patch(f"/api/tasks/{task['id']}", json={"status": "done"}, headers=headers)

    view = client.post("/api/demo/clock", json={"days": 1}, headers=headers).json()["data"]
    assert view["offset_days"] == 1 and view["label"] == "演示用"
    day2 = client.get("/api/plan/today", headers=headers).json()["data"]
    assert day2["date"] == view["today"]
    assert date.fromisoformat(day2["date"]) == date.fromisoformat(day1["date"]) + timedelta(days=1)
    assert len(day2["tasks"]) == 3
    assert day2["tasks"][0]["ref"]["source"] == "mistakes"
    assert day2["tasks"][0]["id"] == day2["first_task_id"]


def test_steps_add_up_and_never_pile_up(client, auth, demo_on):
    headers = auth("demo-skip")
    client.get("/api/plan/today", headers=headers)  # 第一天一件都不做
    client.post("/api/demo/clock", json={"days": 2}, headers=headers)
    view = client.post("/api/demo/clock", json={"days": 8}, headers=headers).json()["data"]
    assert view["offset_days"] == 10
    plan = client.get("/api/plan/today", headers=headers).json()["data"]
    assert plan["date"] == view["today"]
    assert len(plan["tasks"]) <= 3  # 没做的不堆过来
    assert all(task["status"] == "todo" for task in plan["tasks"])


def test_reset_returns_to_the_same_plan_with_records(client, auth, demo_on):
    headers = auth("demo-reset")
    day1 = client.get("/api/plan/today", headers=headers).json()["data"]
    first = day1["tasks"][0]["id"]
    client.patch(f"/api/tasks/{first}", json={"status": "done"}, headers=headers)
    client.post("/api/demo/clock", json={"days": 1}, headers=headers)
    view = client.post("/api/demo/clock/reset", headers=headers).json()["data"]
    assert view["offset_days"] == 0 and view["today"] == view["real_today"]
    back = client.get("/api/plan/today", headers=headers).json()["data"]
    assert back["date"] == day1["date"]
    assert [t["id"] for t in back["tasks"]] == [t["id"] for t in day1["tasks"]]
    assert back["tasks"][0]["status"] == "done"


def test_other_users_are_not_affected(client, auth, demo_on):
    jumper, other = auth("demo-jumper"), auth("demo-other")
    client.post("/api/demo/clock", json={"days": 8}, headers=jumper)
    view = _clock(client, other)
    assert view["offset_days"] == 0
    assert client.get("/api/plan/today", headers=other).json()["data"]["date"] == view["real_today"]


@pytest.mark.parametrize("days", [0, -1, 31])
def test_bad_step_is_rejected(client, auth, demo_on, days):
    response = client.post("/api/demo/clock", json={"days": days}, headers=auth("demo-bad"))
    assert response.status_code == 422
