"""计划线排程引擎：规则单测 + 接口测试。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.study.plan import scheduler
from app.study.plan.scheduler import LectureState, MistakeItem, PlanInputs, ReviewItem

TODAY = date(2026, 11, 10)
YESTERDAY = TODAY - timedelta(days=1)


def lec(n, *, material=True, mastery=None, practiced=None):
    return LectureState(n, f"lec-{n}", f"第 {n} 讲", material, mastery, practiced)


def inputs(**kw):
    base = dict(today=TODAY, goal_active=True, lecture_count=12, learned_up_to=5, lectures=(), mistakes=(), reviews=())
    base.update(kw)
    return PlanInputs(**base)


def kinds(tasks):
    return [t.kind for t in tasks]


# ---------- 规则 ----------


def test_three_sources_one_each_in_default_order():
    tasks = scheduler.schedule(
        inputs(
            lectures=(lec(5, mastery=60), lec(6, material=False)),
            reviews=(ReviewItem("kp1", "风险登记册", "lec-5", 40, TODAY),),
        )
    )
    assert kinds(tasks) == ["learn", "practice", "repair"]
    assert tasks[0].ref == {"source": "upload", "lecture_no": 6, "lecture_id": "lec-6"}
    assert tasks[1].ref["lecture_no"] == 5
    assert tasks[2].ref["source"] == "review"


def test_yesterdays_mistakes_go_first():
    tasks = scheduler.schedule(
        inputs(
            lectures=(lec(5), lec(6)),
            mistakes=(MistakeItem("q1", "lec-5", YESTERDAY), MistakeItem("q2", "lec-5", YESTERDAY)),
        )
    )
    assert tasks[0].kind == "repair"
    assert tasks[0].ref["source"] == "mistakes"
    assert tasks[0].ref["question_ids"] == ["q1", "q2"]
    assert len(tasks) == 3


def test_mistakes_made_today_wait_until_tomorrow():
    tasks = scheduler.schedule(
        inputs(lectures=(lec(5), lec(6)), mistakes=(MistakeItem("q1", "lec-5", TODAY),))
    )
    assert all(t.ref.get("source") != "mistakes" for t in tasks)


def test_empty_source_is_filled_by_others_never_more_than_three():
    # 没有错题、没有复习：补一补空，由练一练和学新的顶上。
    tasks = scheduler.schedule(inputs(lectures=(lec(4, mastery=30), lec(5, mastery=70), lec(6))))
    assert len(tasks) == 3
    assert "repair" not in kinds(tasks)
    practiced = [t.ref["lecture_no"] for t in tasks if t.kind == "practice"]
    assert practiced == [4, 5]  # 掌握度低的先练


def test_only_learn_available_caps_at_two_new_lectures():
    tasks = scheduler.schedule(inputs(learned_up_to=0, lectures=()))
    assert kinds(tasks) == ["learn", "learn"]


def test_lots_of_everything_still_three():
    many = tuple(MistakeItem(f"q{i}", f"lec-{i % 5 + 1}", YESTERDAY) for i in range(30))
    reviews = tuple(ReviewItem(f"kp{i}", f"点{i}", "lec-1", 10, TODAY) for i in range(30))
    tasks = scheduler.schedule(
        inputs(lectures=tuple(lec(n) for n in range(1, 13)), mistakes=many, reviews=reviews)
    )
    assert len(tasks) == 3
    assert set(kinds(tasks)) == {"learn", "practice", "repair"}


def test_paused_goal_or_no_goal_gives_nothing():
    assert scheduler.schedule(inputs(goal_active=False, lectures=(lec(5),))) == []


def test_finished_course_and_no_review_gives_practice_only():
    tasks = scheduler.schedule(inputs(lecture_count=5, learned_up_to=5, lectures=tuple(lec(n) for n in range(1, 6))))
    assert kinds(tasks) == ["practice", "practice", "practice"]


def test_mastered_points_are_not_reviewed():
    tasks = scheduler.schedule(
        inputs(lectures=(lec(5),), reviews=(ReviewItem("kp1", "已掌握", "lec-5", 90, TODAY),))
    )
    assert all(t.ref.get("source") != "review" for t in tasks)


@pytest.mark.parametrize("level,count", [("light", 3), ("normal", 5), ("sprint", 8)])
def test_intensity_changes_amount_not_count(level, count):
    text = scheduler.describe("practice", {"source": "quiz", "lecture_no": 5}, level)
    assert text["title"] == f"第 5 讲做 {count} 道题"


def test_copy_has_no_blame_or_streaks():
    refs = [
        ("learn", {"source": "upload", "lecture_no": 6}),
        ("learn", {"source": "lecture", "lecture_no": 6}),
        ("practice", {"source": "quiz", "lecture_no": 5}),
        ("repair", {"source": "mistakes", "lecture_no": 5, "question_ids": ["a", "b"]}),
        ("repair", {"source": "review", "lecture_no": 5, "point_name": "x"}),
    ]
    for kind, ref in refs:
        for level in ("light", "normal", "sprint"):
            text = " ".join(scheduler.describe(kind, ref, level).values())
            for banned in ("断了", "连续", "没来", "落下", "又错"):
                assert banned not in text


# ---------- 接口 ----------


@pytest.fixture
def clock(monkeypatch):
    """把计划线的“今天”换成可控的日期。"""
    from app.study.plan import service

    state = {"today": service.today_for("x")}
    monkeypatch.setattr(service, "today_for", lambda user_id: state["today"])
    return state


def test_api_replaces_seed_and_keeps_contract(client, auth, clock):
    headers = auth("plan-engine-a")
    body = client.get("/api/plan/today", headers=headers).json()
    data = body["data"]
    assert body["ok"] is True
    assert len(data["tasks"]) == 3
    assert [t["kind"] for t in data["tasks"]] == ["learn", "practice", "repair"]
    # 地基样例写的是“交第 6 讲课件”；引擎按进度排第 7 讲。
    assert data["tasks"][0]["title"] == "交第 7 讲课件"
    assert data["first_task_id"] == data["tasks"][0]["id"]
    for task in data["tasks"]:
        assert task["reason"] and task["amount"] and "minutes" in task
    # 同一天再打开不重新洗牌。
    again = client.get("/api/plan/today", headers=headers).json()["data"]
    assert [t["id"] for t in again["tasks"]] == [t["id"] for t in data["tasks"]]


def test_api_intensity_changes_amount_and_keeps_three(client, auth, clock):
    headers = auth("plan-engine-b")
    client.get("/api/plan/today", headers=headers)
    sprint = client.patch("/api/plan/today", json={"intensity": "sprint"}, headers=headers).json()["data"]
    assert sprint["minutes"] == 50 and len(sprint["tasks"]) == 3
    assert sum(t["minutes"] for t in sprint["tasks"]) == 50
    practice = next(t for t in sprint["tasks"] if t["kind"] == "practice")
    assert practice["title"] == "第 6 讲做 8 道题"


def test_api_next_day_mistakes_first_and_progress_moves(client, auth, clock):
    headers = auth("plan-engine-c")
    day1 = client.get("/api/plan/today", headers=headers).json()["data"]
    user_qid = "plan-engine-c:q1"
    wrong = client.post("/api/attempts", json={"question_id": user_qid, "answer": "A"}, headers=headers)
    assert wrong.json()["data"]["correct"] is False
    # 勾完今天三件。
    for task in day1["tasks"]:
        client.patch(f"/api/tasks/{task['id']}", json={"status": "done"}, headers=headers)
    done = client.get("/api/plan/today", headers=headers).json()["data"]
    assert done["all_done"] is True and done["first_task_id"] is None

    clock["today"] = clock["today"] + timedelta(days=1)
    day2 = client.get("/api/plan/today", headers=headers).json()["data"]
    assert day2["date"] != day1["date"]
    assert day2["intensity"] == "normal"
    assert len(day2["tasks"]) == 3
    assert all(t["status"] == "todo" for t in day2["tasks"])
    first = day2["tasks"][0]
    assert first["kind"] == "repair" and first["ref"]["source"] == "mistakes"
    assert first["id"] == day2["first_task_id"]
    # 昨天学（交）了第 7 讲，今天学新的排第 8 讲。
    learn = next(t for t in day2["tasks"] if t["kind"] == "learn")
    assert learn["ref"]["lecture_no"] == 8

    # 昨天的完成记录还在。
    clock["today"] = clock["today"] - timedelta(days=1)
    back = client.get("/api/plan/today", headers=headers).json()["data"]
    assert all(t["status"] == "done" for t in back["tasks"])


def test_api_untick_learn_rolls_progress_back(client, auth, clock):
    headers = auth("plan-engine-d")
    day1 = client.get("/api/plan/today", headers=headers).json()["data"]
    learn = next(t for t in day1["tasks"] if t["kind"] == "learn")
    client.patch(f"/api/tasks/{learn['id']}", json={"status": "done"}, headers=headers)
    client.patch(f"/api/tasks/{learn['id']}", json={"status": "todo"}, headers=headers)
    clock["today"] = clock["today"] + timedelta(days=1)
    day2 = client.get("/api/plan/today", headers=headers).json()["data"]
    assert next(t for t in day2["tasks"] if t["kind"] == "learn")["ref"]["lecture_no"] == 7


# ---------- V2.1：学、练、考 ----------


def test_v2_fixed_learn_practice_exam_on_next_lecture():
    tasks = scheduler.schedule(inputs(v2=True, lecture_count=10, learned_up_to=0, lectures=tuple(lec(n) for n in range(1, 11))))
    assert kinds(tasks) == ["learn", "practice", "exam"]
    assert {t.ref["lecture_no"] for t in tasks} == {1}
    assert tasks[0].ref["source"] == "lecture" and tasks[2].ref["mistake_ids"] == []


def test_v2_exam_takes_old_mistakes_but_not_today():
    wrong = (MistakeItem("q2", "lec-1", YESTERDAY), MistakeItem("q1", "lec-2", YESTERDAY - timedelta(days=1)), MistakeItem("q3", "lec-2", TODAY))
    tasks = scheduler.schedule(inputs(v2=True, lecture_count=5, learned_up_to=2, lectures=tuple(lec(n) for n in range(1, 6)), mistakes=wrong))
    assert kinds(tasks) == ["learn", "practice", "exam"]  # 错题不再单独排「补一补」
    assert tasks[0].ref["lecture_no"] == 3 and tasks[2].ref["mistake_ids"] == ["q1", "q2"]


def test_v2_all_learned_keeps_practice_and_exam_on_last_lecture():
    tasks = scheduler.schedule(inputs(v2=True, lecture_count=3, learned_up_to=3, lectures=tuple(lec(n) for n in range(1, 4))))
    assert kinds(tasks) == ["practice", "exam"] and tasks[0].ref["lecture_no"] == 3


def test_v2_exam_text_follows_intensity():
    ref = {"source": "exam", "lecture_no": 2, "mistake_ids": ["a", "b"]}
    assert scheduler.describe("exam", ref, "light")["amount"] == "3 道单选题，含 2 道之前的错题"
    assert scheduler.describe("exam", {"lecture_no": 2}, "sprint")["amount"] == "8 道单选题，都是第 2 讲的题"


def test_v2_off_keeps_mvp_rules():
    tasks = scheduler.schedule(inputs(lecture_count=10, learned_up_to=0, lectures=tuple(lec(n) for n in range(1, 11))))
    assert kinds(tasks) == ["learn", "learn"]
