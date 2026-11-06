"""计划线 · 小满开场（AI 能力“开场与建议”）和给看板的计划数据。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.study.plan import opening
from app.study.plan.returning import BANNED_WORDS


@pytest.fixture
def demo_on(monkeypatch):
    monkeypatch.setenv("XIAOMAN_DEMO_CLOCK", "1")


def _open(client, headers):
    return client.get("/api/plan/opening", headers=headers).json()["data"]


def _plan(client, headers):
    return client.get("/api/plan/today", headers=headers).json()["data"]


def _confirm_goal(client, headers, **answers):
    card = client.post("/api/goals/draft", json={"title": "考过 PMP", **answers}, headers=headers).json()["data"]
    client.post(f"/api/suggestions/{card['id']}/accept", headers=headers)


# ---------- 规则开场白 ----------


@pytest.mark.parametrize(
    "facts,expect",
    [
        ({"needs_setup": True}, "想学成什么样"),
        ({"paused": True}, "随时回来"),
        ({"has_card": True}, "先看看这样安排行不行"),
        ({"last_mistakes": {"lecture_no": 6, "count": 2}, "last_was_yesterday": True}, "昨天第 6 讲有 2 道没做对"),
        ({"last_mistakes": {"lecture_no": 6, "count": 1}}, "上次第 6 讲有 1 道没做对"),
        ({"first_visit": True}, "先做第一件"),
        ({"first_task": "交第 7 讲课件"}, "先做「交第 7 讲课件」"),
    ],
)
def test_rule_greeting(facts, expect):
    text = opening.rule_greeting(facts)
    assert expect in text and len(text) <= opening.MAX_CHARS
    for word in BANNED_WORDS:
        assert word not in text


# ---------- 接口：没 key 时走规则 ----------


def test_first_meeting_invites_goal_and_is_cached(client, auth):
    headers = auth("open-first")
    first = _open(client, headers)
    assert "想学成什么样" in first["greeting"] and first["source"] == "rule" and first["cached"] is False
    again = _open(client, headers)
    assert again["cached"] is True and again["greeting"] == first["greeting"]
    usage = client.get("/api/study/usage", headers=headers).json()["data"]
    assert usage["by_capability"]["开场与建议"]["calls"] == 1  # 记了 token；第二次走缓存，不再调用


def test_day_two_opens_with_yesterdays_mistakes(client, auth, demo_on):
    headers = auth("open-day2")
    _confirm_goal(client, headers, learned_up_to="第 6 讲", lecture_count="12 讲")
    client.post("/api/attempts", json={"question_id": "open-day2:q1", "answer": "A"}, headers=headers)
    client.post("/api/demo/clock", json={"days": 1}, headers=headers)
    text = _open(client, headers)["greeting"]
    assert "昨天第 6 讲有 1 道没做对" in text


def test_return_after_days_does_not_mention_the_gap(client, auth, demo_on):
    headers = auth("open-return")
    _confirm_goal(client, headers)
    client.post("/api/demo/clock", json={"days": 3}, headers=headers)
    text = _open(client, headers)["greeting"]
    assert "先看看这样安排行不行" in text
    for word in ("3 天", "三天", "几天", "断", "没来"):
        assert word not in text


# ---------- 接口：有 key 时，语气不合格要重试、兜底、写 bad case ----------


def test_ai_output_with_blame_is_retried_then_falls_back(client, auth, monkeypatch):
    calls = []

    def fake_chat_json(system, user, **kwargs):
        calls.append(system)
        return {"greeting": "你又好几天没来了，断了可不行", "_model": "fake", "_mode": "live"}

    monkeypatch.setattr(opening, "has_llm", lambda task=None: True)
    monkeypatch.setattr(opening, "chat_json", fake_chat_json)
    headers = auth("open-ai-bad")
    data = _open(client, headers)
    assert len(calls) == 2 and "没通过检查" in calls[1]
    assert data["source"] == "rule" and "想学成什么样" in data["greeting"]
    cases = client.get("/api/study/bad-cases", headers=headers).json()["data"]
    items = cases.get("items", [])
    assert any(item.get("capability") == "开场与建议" and item.get("problem_type") == "语气不对" for item in items)


def test_ai_output_ok_is_used_and_labelled(client, auth, monkeypatch):
    monkeypatch.setattr(opening, "has_llm", lambda task=None: True)
    monkeypatch.setattr(
        opening, "chat_json", lambda system, user, **kw: {"greeting": "早呀，今天先做第一件就好。", "_model": "fake", "_mode": "live"}
    )
    data = _open(client, auth("open-ai-ok"))
    assert data["source"] == "ai" and data["greeting"] == "早呀，今天先做第一件就好。"
    assert data["label"] == "AI 整理，可以改"


def test_facts_do_not_include_days_away(client, auth, demo_on):
    from app.data_access.session import SessionLocal
    from app.study.plan import service

    headers = auth("open-facts")
    _confirm_goal(client, headers)
    client.post("/api/demo/clock", json={"days": 8}, headers=headers)
    _plan(client, headers)
    with SessionLocal() as session:
        facts = opening.gather_facts(session, "open-facts", service.today_for("open-facts"))
    assert not any("away" in key or "gap" in key for key in facts)
    assert facts["has_card"] is True


# ---------- 给看板的数据 ----------


def test_progress_counts_days_with_done_tasks_this_week(client, auth, monkeypatch):
    from app.study.plan import service

    state = {"today": date(2026, 11, 11)}  # 周三
    monkeypatch.setattr(service, "today_for", lambda user_id: state["today"])
    headers = auth("open-progress")
    card = client.post(
        "/api/goals/draft",
        json={"title": "PMP", "exam_date": "2026-12-20", "lecture_count": "10 讲", "learned_up_to": "第 2 讲"},
        headers=headers,
    ).json()["data"]
    client.post(f"/api/suggestions/{card['id']}/accept", headers=headers)
    plan = _plan(client, headers)
    learn = next(t for t in plan["tasks"] if t["kind"] == "learn")
    client.patch(f"/api/tasks/{learn['id']}", json={"status": "done"}, headers=headers)
    state["today"] = date(2026, 11, 12)
    _plan(client, headers)  # 打开了但一件没做，不算学了
    state["today"] = date(2026, 11, 13)
    plan = _plan(client, headers)
    other = next(t for t in plan["tasks"] if t["kind"] != "learn")
    client.patch(f"/api/tasks/{other['id']}", json={"status": "done"}, headers=headers)

    data = client.get("/api/plan/progress", headers=headers).json()["data"]
    assert data["week_start"] == "2026-11-09"
    assert data["studied_days_this_week"] == 2
    assert data["learned_up_to"] == 3 and data["lecture_count"] == 10 and data["goal_progress"] == 0.3
    assert data["days_to_exam"] == (date(2026, 12, 20) - date(2026, 11, 13)).days
    assert data["phase"] == "学新讲"
    assert "连续" not in str(data)

    state["today"] = date(2026, 11, 16)  # 下周一，重新数
    assert client.get("/api/plan/progress", headers=headers).json()["data"]["studied_days_this_week"] == 0
    assert timedelta  # noqa
