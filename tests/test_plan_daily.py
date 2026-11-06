"""计划线 · 收工卡、引导下一件、“只有 15 分钟”建议卡、快捷回复（PRD F5）。"""

from __future__ import annotations

import pytest

from app.study.plan import daily
from app.study.plan.returning import BANNED_WORDS


@pytest.mark.parametrize(
    "text,level",
    [
        ("今天只有15分钟", "light"),
        ("今天只有十五分钟", "light"),
        ("今天有半小时", "normal"),
        ("今天有一个小时", "sprint"),
        ("今天好累", "light"),
        ("今天想多学点", "sprint"),
        ("换成冲刺", "sprint"),
        ("你好", None),
    ],
)
def test_wanted_intensity(text, level):
    assert daily.wanted_intensity(text) == level


def test_quick_replies_only_make_sense_now():
    task = {"id": "t1", "title": "交第 7 讲课件"}
    base = dict(needs_setup=False, has_card=False, first_task=task, all_done=False, has_tasks=True)
    light = [r["text"] for r in daily.quick_replies(intensity="light", **base)]
    assert "今天只有 15 分钟" not in light and "今天想多学点" in light
    sprint = [r["text"] for r in daily.quick_replies(intensity="sprint", **base)]
    assert "今天想多学点" not in sprint and "今天只有 15 分钟" in sprint
    assert daily.quick_replies(intensity="normal", **dict(base, has_card=True)) == []
    assert daily.quick_replies(intensity="normal", **dict(base, needs_setup=True))[0]["action"] == "goal_setup"
    done = [r["action"] for r in daily.quick_replies(intensity="normal", **dict(base, all_done=True, first_task=None))]
    assert done == ["tomorrow", "dashboard"]


def test_copy_has_no_blame_words():
    texts = [daily.same_level_reply(level) for level in ("light", "normal", "sprint")]
    for level in ("light", "normal", "sprint"):
        card = daily.adjust_card(level)
        texts += card["lines"] + [card["title"], card["collapsed_text"]]
    card = daily.done_card([{"kind_label": "学新的", "title": "x"}], [], milestone="第 7 讲学完了")
    texts += card["lines"] + [card["title"]]
    for text in texts:
        for word in BANNED_WORDS:
            assert word not in text


# ---------- 接口 ----------


@pytest.fixture
def demo_on(monkeypatch):
    monkeypatch.setenv("XIAOMAN_DEMO_CLOCK", "1")


def _plan(client, headers):
    return client.get("/api/plan/today", headers=headers).json()["data"]


def test_ticking_guides_to_next_and_ends_with_done_card(client, auth):
    headers = auth("daily-done")
    plan = _plan(client, headers)
    assert plan["done_card"] is None and plan["mood"] == "hello"
    first = client.patch(f"/api/tasks/{plan['tasks'][0]['id']}", json={"status": "done"}, headers=headers).json()["data"]
    assert first["next"]["task_id"] == plan["tasks"][1]["id"]
    assert [o["label"] for o in first["next"]["options"]] == ["开始", "晚点再做"]
    assert first["all_done"] is False
    client.patch(f"/api/tasks/{plan['tasks'][1]['id']}", json={"status": "done"}, headers=headers)
    last = client.patch(f"/api/tasks/{plan['tasks'][2]['id']}", json={"status": "done"}, headers=headers).json()["data"]
    assert last["all_done"] is True and last["next"] is None
    card = last["done_card"]
    assert card["type"] == "done" and card["options"][0]["label"] == "看看板"
    assert len(card["tomorrow"]) == 3
    assert any(line.startswith("明天的三件：") for line in card["lines"])
    assert "第 7 讲的课件交上了" in card["lines"]
    assert _plan(client, headers)["mood"] == "celebrate"


def test_done_card_preview_matches_tomorrow_and_puts_mistakes_first(client, auth, demo_on):
    headers = auth("daily-preview")
    plan = _plan(client, headers)
    client.post("/api/attempts", json={"question_id": "daily-preview:q1", "answer": "A"}, headers=headers)
    for task in plan["tasks"]:
        client.patch(f"/api/tasks/{task['id']}", json={"status": "done"}, headers=headers)
    preview = _plan(client, headers)["done_card"]["tomorrow"]
    assert preview[0]["kind"] == "repair" and preview[0]["ref"]["source"] == "mistakes"
    client.post("/api/demo/clock", json={"days": 1}, headers=headers)
    tomorrow = _plan(client, headers)
    assert [t["title"] for t in tomorrow["tasks"]] == [t["title"] for t in preview]


def test_later_moves_task_to_the_end(client, auth):
    headers = auth("daily-later")
    plan = _plan(client, headers)
    first = plan["tasks"][0]["id"]
    after = client.post(f"/api/tasks/{first}/later", headers=headers).json()["data"]
    assert after["tasks"][-1]["id"] == first and after["first_task_id"] != first
    assert len(after["tasks"]) == 3


def test_only_15_minutes_gives_a_card_that_applies_on_click(client, auth):
    headers = auth("daily-adjust")
    _plan(client, headers)
    res = client.post("/api/plan/adjust", json={"text": "今天只有15分钟"}, headers=headers).json()["data"]
    card = res["card"]
    assert card["kind"] == "adjust_intensity" and card["title"] == "今天换成轻松"
    assert _plan(client, headers)["intensity"] == "normal"  # 没点之前不变
    assert _plan(client, headers)["quick_replies"] == []  # 有卡时先处理卡
    again = client.post("/api/plan/adjust", json={"text": "想多学点"}, headers=headers).json()["data"]
    assert again["card"]["id"] == card["id"]  # 一次只一张
    accepted = client.post(f"/api/suggestions/{card['id']}/accept", headers=headers).json()["data"]
    assert accepted["plan"]["intensity"] == "light" and len(accepted["plan"]["tasks"]) == 3
    assert sum(t["minutes"] for t in accepted["plan"]["tasks"]) == 15
    same = client.post("/api/plan/adjust", json={"text": "今天只有15分钟"}, headers=headers).json()["data"]
    assert same["card"] is None and "已经是轻松" in same["reply"]
    undone = client.post(f"/api/actions/{card['id']}/undo", headers=headers).json()["data"]
    assert undone["plan"]["intensity"] == "normal"


def test_adjust_not_understood(client, auth):
    res = client.post("/api/plan/adjust", json={"text": "你好呀"}, headers=auth("daily-huh")).json()["data"]
    assert res["understood"] is False and res["card"] is None and "15 分钟" in res["reply"]


def test_quick_replies_endpoint(client, auth):
    headers = auth("daily-qr")
    items = client.get("/api/plan/quick-replies", headers=headers).json()["data"]["items"]
    assert [i["action"] for i in items] == ["goal_setup"]  # 还没定目标，先定目标
    card = client.post("/api/goals/draft", json={"title": "考过 PMP"}, headers=headers).json()["data"]
    client.post(f"/api/suggestions/{card['id']}/accept", headers=headers)
    items = client.get("/api/plan/quick-replies", headers=headers).json()["data"]["items"]
    texts = [i["text"] for i in items]
    assert texts[0].startswith("开始：") and "今天只有 15 分钟" in texts and "今天想多学点" in texts
