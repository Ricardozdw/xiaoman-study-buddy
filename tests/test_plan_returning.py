"""计划线 · 中断后回来（PRD F6）：规则单测 + 接口测试。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.study.plan import returning
from app.study.plan.returning import ReturnContext

TODAY = date(2026, 11, 20)


def ctx(**kw):
    base = dict(
        today=TODAY,
        last_open=TODAY - timedelta(days=3),
        goal_active=True,
        exam_date=TODAY + timedelta(days=40),
        lecture_count=12,
        learned_up_to=6,
    )
    base.update(kw)
    return ReturnContext(**base)


# ---------- 规则 ----------


@pytest.mark.parametrize("away,expected", [(1, None), (2, "return_light"), (7, "return_light"), (8, "return_goal"), (30, "return_goal")])
def test_classify_by_days_away(away, expected):
    assert returning.classify(ctx(last_open=TODAY - timedelta(days=away))) == expected


def test_first_visit_or_paused_goal_gives_no_card():
    assert returning.classify(ctx(last_open=None)) is None
    assert returning.classify(ctx(goal_active=False)) is None


def test_no_exam_date_is_light():
    assert returning.classify(ctx(exam_date=None)) == "return_light"


def test_tight_schedule_gives_reschedule_with_three_options():
    # 离考试 10 天，还有 6 讲 → 空余 4 天，低于复习底线 7 天。
    c = ctx(exam_date=TODAY + timedelta(days=10))
    assert returning.spare_days(c) == 4
    assert returning.classify(c) == "return_reschedule"
    options = returning.reschedule_options(c)
    assert [o["id"] for o in options] == ["catch_up_sprint", "compress_review", "skim_some"]
    sprint = options[0]["effect"]
    assert sprint["pace"]["per_task"] == 2 and sprint["intensity"] == "sprint"
    assert sprint["pace"]["until"] == (TODAY + timedelta(days=2)).isoformat()  # 3 天
    assert options[1]["effect"] == {"review_floor": 4}


def test_no_spare_time_hides_compress_option():
    c = ctx(exam_date=TODAY + timedelta(days=6))  # 空余 0 天
    assert [o["id"] for o in returning.reschedule_options(c)] == ["catch_up_sprint", "skim_some"]


def test_one_lecture_left_and_no_spare_falls_back_to_light():
    c = ctx(exam_date=TODAY + timedelta(days=1), learned_up_to=11)
    assert returning.reschedule_options(c) == []
    assert returning.classify(c) == "return_light"


def test_exam_date_passed_asks_about_goal():
    assert returning.classify(ctx(exam_date=TODAY - timedelta(days=1))) == "return_goal"


def test_card_copy_has_no_blame_words():
    contexts = [
        ctx(),
        ctx(exam_date=None),
        ctx(exam_date=TODAY + timedelta(days=10)),
        ctx(exam_date=TODAY + timedelta(days=6)),
        ctx(last_open=TODAY - timedelta(days=20)),
    ]
    for c in contexts:
        for kind in (returning.KIND_LIGHT, returning.KIND_RESCHEDULE, returning.KIND_GOAL):
            text = returning.card_text(returning.build_card(kind, c))
            for word in returning.BANNED_WORDS:
                assert word not in text, (kind, word, text)


def test_goal_card_options():
    card = returning.build_card(returning.KIND_GOAL, ctx())
    assert [o["id"] for o in card["options"]] == ["keep", "exam_date", "rest"]
    assert card["options"][1]["needs"] == "exam_date"


# ---------- 接口（配合演示开关跳日期）----------


@pytest.fixture
def demo_on(monkeypatch):
    monkeypatch.setenv("XIAOMAN_DEMO_CLOCK", "1")


def _today(client, headers):
    return client.get("/api/plan/today", headers=headers).json()["data"]


def _jump(client, headers, days):
    return client.post("/api/demo/clock", json={"days": days}, headers=headers).json()["data"]


def _set_goal(client, headers, exam: date, lectures: int = 12):
    client.post(
        "/api/goals",
        json={"title": "PMP", "exam_date": exam.isoformat(), "lecture_count": lectures, "daily_minutes": 30},
        headers=headers,
    )


def _accept(client, headers, card_id, **body):
    return client.post(f"/api/suggestions/{card_id}/accept", json=body or None, headers=headers)


def _pending_plan_cards(client, headers):
    items = client.get("/api/suggestions", headers=headers).json()["data"]["items"]
    return [i for i in items if i["status"] == "pending" and i["suggestion"].get("plan_line")]


def test_next_day_has_no_card(client, auth, demo_on):
    headers = auth("ret-next")
    _today(client, headers)
    _jump(client, headers, 1)
    assert _today(client, headers)["card"] is None


def test_two_days_without_exam_date_light_card_accept_and_undo(client, auth, demo_on):
    headers = auth("ret-light")
    _today(client, headers)
    _jump(client, headers, 2)
    plan = _today(client, headers)
    card = plan["card"]
    assert card["kind"] == "return_light" and card["status"] == "pending"
    assert plan["intensity"] == "normal" and len(plan["tasks"]) == 3  # 点了才生效；没做的不堆过来
    assert all("effect" not in option for option in card["options"])

    accepted = _accept(client, headers, card["id"]).json()["data"]
    assert accepted["status"] == "executed" and accepted["chosen"] == "light_today"
    assert accepted["plan"]["intensity"] == "light" and accepted["plan"]["card"] is None
    assert len(accepted["plan"]["tasks"]) == 3

    undone = client.post(f"/api/actions/{card['id']}/undo", headers=headers).json()["data"]
    assert undone["status"] == "undone"
    assert undone["plan"]["intensity"] == "normal"


def test_dismiss_changes_nothing(client, auth, demo_on):
    headers = auth("ret-dismiss")
    _today(client, headers)
    _jump(client, headers, 3)
    card = _today(client, headers)["card"]
    dismissed = client.post(f"/api/suggestions/{card['id']}/dismiss", headers=headers).json()["data"]
    assert dismissed["status"] == "declined"
    plan = _today(client, headers)
    assert plan["card"] is None and plan["intensity"] == "normal"
    assert _accept(client, headers, card["id"]).status_code == 422


def test_tight_schedule_reschedule_sprint_changes_plan_and_undo_restores(client, auth, demo_on):
    headers = auth("ret-sprint")
    day0 = date.fromisoformat(_today(client, headers)["date"])
    _set_goal(client, headers, day0 + timedelta(days=12))  # 第 2 天：离考试 10 天，6 讲没学 → 空余 4
    _jump(client, headers, 2)
    plan = _today(client, headers)
    card = plan["card"]
    assert card["kind"] == "return_reschedule" and card["type"] == "reschedule"
    assert [o["id"] for o in card["options"]] == ["catch_up_sprint", "compress_review", "skim_some"]
    assert _accept(client, headers, card["id"]).status_code == 422  # 多个选项必须选一个

    accepted = _accept(client, headers, card["id"], option="catch_up_sprint").json()["data"]
    today = accepted["plan"]
    assert today["intensity"] == "sprint" and len(today["tasks"]) == 3
    learn = next(t for t in today["tasks"] if t["kind"] == "learn")
    assert learn["ref"]["lecture_nos"] == [7, 8]
    assert learn["title"] == "交第 7、8 讲课件"

    # 明天还在补课期：默认冲刺、一次两讲。
    client.patch(f"/api/tasks/{learn['id']}", json={"status": "done"}, headers=headers)
    _jump(client, headers, 1)
    tomorrow = _today(client, headers)
    assert tomorrow["intensity"] == "sprint"
    assert next(t for t in tomorrow["tasks"] if t["kind"] == "learn")["ref"]["lecture_nos"] == [9, 10]
    client.post("/api/demo/clock", json={"days": 1}, headers=headers)  # 先离开这一天
    client.post("/api/demo/clock/reset", headers=headers)
    _jump(client, headers, 2)  # 回到选卡那天，撤销

    undone = client.post(f"/api/actions/{card['id']}/undo", headers=headers).json()["data"]
    assert undone["plan"]["intensity"] == "normal"
    learn_after = [t for t in undone["plan"]["tasks"] if t["kind"] == "learn"]
    done_kept = [t for t in undone["plan"]["tasks"] if t["status"] == "done"]
    assert done_kept and done_kept[0]["ref"]["lecture_nos"] == [7, 8]  # 完成记录不丢
    assert len(undone["plan"]["tasks"]) <= 3
    assert all("lecture_nos" not in t["ref"] for t in learn_after if t["status"] == "todo")


def test_skim_option_marks_learning_as_key_points_only(client, auth, demo_on):
    headers = auth("ret-skim")
    day0 = date.fromisoformat(_today(client, headers)["date"])
    _set_goal(client, headers, day0 + timedelta(days=12))
    _jump(client, headers, 2)
    card = _today(client, headers)["card"]
    plan = _accept(client, headers, card["id"], option="skim_some").json()["data"]["plan"]
    learn = next(t for t in plan["tasks"] if t["kind"] == "learn")
    # 第 7、8 讲课件还没交，先交课件；交了以后按“只看要点”学（见下面的规则测试）。
    assert learn["ref"]["mode"] == "skim" and learn["ref"]["lecture_nos"] == [7, 8]
    assert learn["title"] == "交第 7、8 讲课件"
    assert plan["intensity"] == "normal"


def test_skim_and_sprint_copy_for_two_lectures():
    from app.study.plan import scheduler

    skim = scheduler.describe("learn", {"source": "lecture", "lecture_no": 7, "lecture_nos": [7, 8], "mode": "skim"}, "normal")
    assert skim["title"] == "学第 7、8 讲" and skim["amount"] == "只看要点"
    sprint = scheduler.describe("learn", {"source": "lecture", "lecture_no": 7, "lecture_nos": [7, 8], "mode": "sprint"}, "sprint")
    assert sprint["title"] == "学第 7、8 讲" and sprint["amount"] == "看完整学习文档"


def test_eight_days_goal_card_rest_then_undo(client, auth, demo_on):
    headers = auth("ret-rest")
    _today(client, headers)
    _jump(client, headers, 8)
    card = _today(client, headers)["card"]
    assert card["kind"] == "return_goal"
    rested = _accept(client, headers, card["id"], option="rest").json()["data"]
    assert rested["plan"]["tasks"] == []
    assert client.get("/api/goals/current", headers=headers).json()["data"]["status"] == "paused"

    undone = client.post(f"/api/actions/{card['id']}/undo", headers=headers).json()["data"]
    assert len(undone["plan"]["tasks"]) == 3
    assert client.get("/api/goals/current", headers=headers).json()["data"]["status"] == "active"


def test_rest_means_no_more_tasks_on_later_days(client, auth, demo_on):
    headers = auth("ret-rest-later")
    _today(client, headers)
    _jump(client, headers, 8)
    card = _today(client, headers)["card"]
    _accept(client, headers, card["id"], option="rest")
    _jump(client, headers, 1)
    later = _today(client, headers)
    assert later["tasks"] == [] and later["card"] is None


def test_goal_keep_leads_to_one_follow_up_card(client, auth, demo_on):
    headers = auth("ret-keep")
    day0 = date.fromisoformat(_today(client, headers)["date"])
    _set_goal(client, headers, day0 + timedelta(days=14))  # 第 8 天：离考试 6 天，6 讲没学 → 空余 0
    _jump(client, headers, 8)
    card = _today(client, headers)["card"]
    assert card["kind"] == "return_goal"
    kept = _accept(client, headers, card["id"], option="keep").json()["data"]
    follow = kept["next_card"]
    assert follow["kind"] == "return_reschedule"
    assert [o["id"] for o in follow["options"]] == ["catch_up_sprint", "skim_some"]
    assert kept["plan"]["card"]["id"] == follow["id"]
    assert len(_pending_plan_cards(client, headers)) == 1  # 一次只一个决定

    # 撤销“照旧”，带出来的下一张也收起。
    client.post(f"/api/actions/{card['id']}/undo", headers=headers)
    assert _pending_plan_cards(client, headers) == []


def test_goal_new_exam_date_needs_a_valid_date(client, auth, demo_on):
    headers = auth("ret-date")
    _today(client, headers)
    view = _jump(client, headers, 8)
    card = _today(client, headers)["card"]
    assert _accept(client, headers, card["id"], option="exam_date").status_code == 422
    assert _accept(client, headers, card["id"], option="exam_date", exam_date=view["today"]).status_code == 422
    new_exam = (date.fromisoformat(view["today"]) + timedelta(days=60)).isoformat()
    accepted = _accept(client, headers, card["id"], option="exam_date", exam_date=new_exam).json()["data"]
    assert accepted["status"] == "executed"
    assert client.get("/api/goals/current", headers=headers).json()["data"]["exam_date"] == new_exam
    assert accepted["next_card"]["kind"] == "return_light"  # 时间宽裕，只建议今天轻松一点

    client.post(f"/api/actions/{card['id']}/undo", headers=headers)
    assert client.get("/api/goals/current", headers=headers).json()["data"]["exam_date"] == ""


def test_unpicked_card_expires_next_day(client, auth, demo_on):
    headers = auth("ret-expire")
    _today(client, headers)
    _jump(client, headers, 2)
    card = _today(client, headers)["card"]
    _jump(client, headers, 1)
    assert _today(client, headers)["card"] is None
    assert _accept(client, headers, card["id"]).status_code == 422


def test_accept_keeps_done_tasks_and_never_exceeds_three(client, auth, demo_on):
    headers = auth("ret-keepdone")
    day0 = date.fromisoformat(_today(client, headers)["date"])
    _set_goal(client, headers, day0 + timedelta(days=12))
    _jump(client, headers, 2)
    plan = _today(client, headers)
    first = plan["tasks"][0]
    client.patch(f"/api/tasks/{first['id']}", json={"status": "done"}, headers=headers)
    after = _accept(client, headers, plan["card"]["id"], option="catch_up_sprint").json()["data"]["plan"]
    assert len(after["tasks"]) <= 3
    assert any(t["id"] == first["id"] and t["status"] == "done" for t in after["tasks"])


def test_foundation_sample_suggestion_still_works(client, auth, demo_on):
    headers = auth("ret-sample")
    items = client.get("/api/suggestions", headers=headers).json()["data"]["items"]
    sample = next(i for i in items if not i["suggestion"].get("plan_line"))
    assert client.post(f"/api/suggestions/{sample['id']}/accept", headers=headers).json()["data"]["status"] == "executed"
    assert client.post(f"/api/suggestions/{sample['id']}/dismiss", headers=headers).status_code == 404
