"""计划线 · 目标拆解（PRD F1）：解析、拆解规则、接口。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.study.plan import goal, parse

TODAY = date(2026, 11, 6)


# ---------- 解析一句话 ----------


@pytest.mark.parametrize(
    "text,expected",
    [("十二", 12), ("二十", 20), ("二十五", 25), ("十", 10), ("一百", 100), ("两", 2), ("七", 7), ("abc", None)],
)
def test_chinese_numbers(text, expected):
    assert parse.cn_to_int(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("12月20日", "2026-12-20"),
        ("十二月二十号", "2026-12-20"),
        ("2027-01-15", "2027-01-15"),
        ("2027年3月1日", "2027-03-01"),
        ("3月1日", "2027-03-01"),  # 今年已过，算明年
        ("一个月后", "2026-12-06"),
        ("两个月后", "2027-01-05"),
        ("3周后", "2026-11-27"),
        ("下个月", "2026-12-06"),
        ("还没定", parse.NO_DATE),
        ("随便", None),
    ],
)
def test_parse_date(text, expected):
    assert parse.parse_date(text, TODAY) == expected


@pytest.mark.parametrize(
    "text,expected",
    [("30 分钟", 30), ("半小时", 30), ("1小时", 60), ("一个半小时", 90), ("两小时", 120), ("20", 20), ("很多", None)],
)
def test_parse_minutes(text, expected):
    assert parse.parse_minutes(text) == expected


def test_parse_lectures_and_progress():
    assert parse.parse_lecture_count("12 讲") == 12
    assert parse.parse_lecture_count("一共十二讲") == 12
    assert parse.parse_lecture_count("不清楚") is None
    assert parse.parse_learned("还没开始") == 0
    assert parse.parse_learned("第 3 讲") == 3
    assert parse.parse_learned("学到第六讲") == 6


def test_revise_one_sentence():
    assert parse.revise("考试改到12月20日", TODAY) == {"exam_date": "2026-12-20"}
    assert parse.revise("每天只有20分钟", TODAY) == {"daily_minutes": 20}
    assert parse.revise("一共10讲", TODAY) == {"lecture_count": 10}
    assert parse.revise("其实我已经学到第3讲了", TODAY) == {"learned_up_to": 3}
    assert parse.revise("默认冲刺吧", TODAY) == {"intensity": "sprint"}
    assert parse.revise("你好", TODAY) == {}


# ---------- 回答 → 取值；默认值不算用户的选择 ----------


def test_skipped_answers_use_defaults_and_are_not_chosen():
    values, chosen, unclear = goal.normalize({"title": "考过 PMP", "lecture_count": "随便"}, TODAY)
    assert values["title"] == "考过 PMP" and chosen["title"] is True
    assert values["lecture_count"] == 12 and chosen["lecture_count"] is False
    assert unclear == ["lecture_count"]
    assert all(chosen[key] is False for key in ("exam_date", "learned_up_to", "daily_minutes"))
    card = goal.build_card(values, chosen, TODAY)
    for key in ("exam_date", "lecture_count", "learned_up_to", "daily_minutes"):
        assert goal.DEFAULT_TEXT[key] in card["lines"]
    assert goal.DEFAULT_TEXT["title"] not in card["lines"]


def test_saying_no_date_is_a_choice():
    values, chosen, _ = goal.normalize({"exam_date": "还没定"}, TODAY)
    assert values["exam_date"] is None and chosen["exam_date"] is True


def test_past_exam_date_is_not_accepted():
    values, chosen, unclear = goal.normalize({"exam_date": "2026-11-01"}, TODAY)
    assert values["exam_date"] is None and chosen["exam_date"] is False and unclear == ["exam_date"]


@pytest.mark.parametrize("minutes,level", [(15, "light"), (20, "light"), (30, "normal"), (50, "sprint")])
def test_default_intensity_from_daily_time(minutes, level):
    assert goal.intensity_for(minutes) == level


# ---------- 拆解规则 ----------


def test_breakdown_phases_with_exam():
    values = dict(goal.DEFAULTS, exam_date="2026-12-06", lecture_count=12, learned_up_to=6)
    plan = goal.breakdown(values, TODAY)  # 30 天，6 讲没学 → 空余 24
    names = [p["name"] for p in plan["phases"]]
    assert names == ["学新讲", "刷题", "冲刺"]
    learn = plan["phases"][0]
    assert learn["start"] == "2026-11-06" and learn["end"] == "2026-11-11" and "第 7–12 讲" in learn["note"]
    assert plan["phases"][2]["end"] == "2026-12-05"
    assert plan["review_floor"] == 7


def test_breakdown_tight_exam_lowers_review_floor_and_says_so_kindly():
    values = dict(goal.DEFAULTS, exam_date="2026-11-10", lecture_count=12, learned_up_to=6)
    plan = goal.breakdown(values, TODAY)  # 4 天，6 讲 → 差 2 讲
    assert plan["review_floor"] == 0
    assert any("还差 2 讲" in note for note in plan["notes"])


def test_breakdown_without_exam():
    plan = goal.breakdown(dict(goal.DEFAULTS), TODAY)
    assert [p["name"] for p in plan["phases"]] == ["学新讲", "刷题"]


def test_card_copy_has_no_blame_words():
    from app.study.plan.returning import BANNED_WORDS

    values = dict(goal.DEFAULTS, exam_date="2026-11-10", lecture_count=12, learned_up_to=6)
    card = goal.build_card(values, {k: True for k in goal.FIELDS}, TODAY)
    text = " ".join(card["lines"] + [card["title"], card["collapsed_text"]])
    for word in BANNED_WORDS:
        assert word not in text


# ---------- 接口 ----------


def _answers(exam: date):
    return {"title": "考过 PMP", "exam_date": exam.isoformat(), "lecture_count": "12 讲", "learned_up_to": "第 6 讲", "daily_minutes": "30 分钟"}


def _plan(client, headers):
    return client.get("/api/plan/today", headers=headers).json()["data"]


def test_questions_have_quick_replies(client, auth):
    data = client.get("/api/goals/questions", headers=auth("goal-q")).json()["data"]
    keys = [q["key"] for q in data["questions"]]
    assert keys == ["title", "exam_date", "lecture_count", "learned_up_to", "daily_minutes"]
    assert all(q["quick_replies"] and q["default_text"].startswith(("先按", "目标先按")) for q in data["questions"])


def test_draft_does_not_change_anything_until_ok(client, auth):
    headers = auth("goal-draft")
    before = _plan(client, headers)
    assert before["needs_setup"] is True
    today = date.fromisoformat(before["date"])
    card = client.post("/api/goals/draft", json=_answers(today + timedelta(days=30)), headers=headers).json()["data"]
    assert card["kind"] == "goal_setup" and card["type"] == "goal" and card["status"] == "pending"
    assert card["options"] == [{"id": "ok", "label": "好"}] and card["revise_label"] == "说说怎么改"
    assert card["defaults_used"] == []
    after = _plan(client, headers)
    assert after["card"]["id"] == card["id"]
    assert after["card"]["revise_label"] == "说说怎么改"
    assert [t["id"] for t in after["tasks"]] == [t["id"] for t in before["tasks"]]  # 没点“好”，左栏不变
    assert client.get("/api/goals/current", headers=headers).json()["data"]["needs_setup"] is True


def test_ok_applies_goal_and_undo_clears_left_column(client, auth):
    headers = auth("goal-ok")
    today = date.fromisoformat(_plan(client, headers)["date"])
    answers = dict(_answers(today + timedelta(days=30)), learned_up_to="第 3 讲", daily_minutes="15 分钟")
    card = client.post("/api/goals/draft", json=answers, headers=headers).json()["data"]
    ok = client.post(f"/api/suggestions/{card['id']}/accept", headers=headers).json()["data"]
    assert ok["status"] == "executed"
    plan = ok["plan"]
    assert plan["needs_setup"] is False and plan["card"] is None
    assert len(plan["tasks"]) == 3 and plan["intensity"] == "light"  # 每天 15 分钟 → 默认轻松
    learn = next(t for t in plan["tasks"] if t["kind"] == "learn")
    assert learn["ref"]["lecture_no"] == 4  # 学到第 3 讲 → 今天第 4 讲
    current = ok["goal"]
    assert current["title"] == "考过 PMP" and current["lecture_count"] == 12 and current["learned_up_to"] == 3
    assert current["chosen"]["daily_minutes"] is True and current["phases"]

    undone = client.post(f"/api/actions/{card['id']}/undo", headers=headers).json()["data"]
    assert undone["status"] == "undone"
    assert undone["plan"]["tasks"] == []  # 撤销后左栏清空
    assert undone["plan"]["needs_setup"] is True
    assert undone["goal"]["status"] == "draft"


def test_undo_keeps_done_tasks(client, auth):
    headers = auth("goal-undo-done")
    plan = _plan(client, headers)
    today = date.fromisoformat(plan["date"])
    card = client.post("/api/goals/draft", json=_answers(today + timedelta(days=30)), headers=headers).json()["data"]
    tasks = client.post(f"/api/suggestions/{card['id']}/accept", headers=headers).json()["data"]["plan"]["tasks"]
    client.patch(f"/api/tasks/{tasks[0]['id']}", json={"status": "done"}, headers=headers)
    undone = client.post(f"/api/actions/{card['id']}/undo", headers=headers).json()["data"]
    assert [t["status"] for t in undone["plan"]["tasks"]] == ["done"]  # 完成记录不丢


def test_revise_makes_a_new_card_and_retires_the_old(client, auth):
    headers = auth("goal-revise")
    today = date.fromisoformat(_plan(client, headers)["date"])
    card = client.post("/api/goals/draft", json={"title": "考过 PMP"}, headers=headers).json()["data"]
    assert set(card["defaults_used"]) == {"exam_date", "lecture_count", "learned_up_to", "daily_minutes"}
    new = client.post(
        f"/api/goals/draft/{card['id']}/revise", json={"text": "每天只有20分钟"}, headers=headers
    ).json()["data"]
    assert new["id"] != card["id"] and new["changed"] == ["daily_minutes"]
    assert "daily_minutes" not in new["defaults_used"]
    assert any("轻松" in line for line in new["lines"])
    assert _plan(client, headers)["card"]["id"] == new["id"]  # 一次只一张
    assert client.post(f"/api/suggestions/{card['id']}/accept", headers=headers).status_code == 422
    bad = client.post(f"/api/goals/draft/{new['id']}/revise", json={"text": "你好"}, headers=headers)
    assert bad.status_code == 422 and "没听懂" in bad.json()["data"]["message"]
    assert today  # 日期只是确认页面打开过


def test_draft_replaces_a_pending_return_card(client, auth, monkeypatch):
    monkeypatch.setenv("XIAOMAN_DEMO_CLOCK", "1")
    headers = auth("goal-vs-return")
    _plan(client, headers)
    client.post("/api/demo/clock", json={"days": 3}, headers=headers)
    assert _plan(client, headers)["card"]["kind"] == "return_light"
    card = client.post("/api/goals/draft", json={"title": "考过 PMP"}, headers=headers).json()["data"]
    assert _plan(client, headers)["card"]["id"] == card["id"]


def test_new_day_starts_at_goal_default_intensity(client, auth, monkeypatch):
    monkeypatch.setenv("XIAOMAN_DEMO_CLOCK", "1")
    headers = auth("goal-default-level")
    today = date.fromisoformat(_plan(client, headers)["date"])
    answers = dict(_answers(today + timedelta(days=30)), daily_minutes="一小时")
    card = client.post("/api/goals/draft", json=answers, headers=headers).json()["data"]
    client.post(f"/api/suggestions/{card['id']}/accept", headers=headers)
    client.patch("/api/plan/today", json={"intensity": "light"}, headers=headers)  # 今天自己切轻松
    client.post("/api/demo/clock", json={"days": 1}, headers=headers)
    assert _plan(client, headers)["intensity"] == "sprint"  # 明天回到目标的默认档


def test_direct_goal_edit_keeps_progress(client, auth):
    headers = auth("goal-direct")
    _plan(client, headers)
    saved = client.post(
        "/api/goals", json={"title": "新目标", "exam_date": "2027-01-01", "lecture_count": 10, "daily_minutes": 40}, headers=headers
    ).json()["data"]
    assert saved["card_type"] == "goal" and saved["learned_up_to"] == 6
    assert saved["chosen"]["lecture_count"] is True


def test_seed_twice_is_harmless_when_rows_already_exist(monkeypatch):
    """并发首次访问：第二个请求在“检查后、写入前”被另一个请求抢先写入时，不能报 500。"""
    from uuid import uuid4
    from app.study.common import store
    from app.study.common.models import PlanDay
    user = f"seed-race-{uuid4().hex}"
    store.seed(user)
    # 模拟“检查时还没有”：让存在性检查查不到，第二次写入就会撞主键
    real_select = store.select
    monkeypatch.setattr(store, "select", lambda *a, **k: real_select(PlanDay.id).where(PlanDay.user_id == "__nobody__"))
    store.seed(user)  # 不抛异常即通过
