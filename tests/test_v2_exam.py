"""V2.1 块3-B：每天的考试（固定第 3 件）、错题并入、阶段当天并成阶段测验。"""
from uuid import uuid4

import pytest
from fastapi import FastAPI

from app.study.plan import scheduler
from tests.conftest import RawTestClient

BASE = "/api/v2/exam"


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("XIAOMAN_DEMO_CLOCK", "1")
    monkeypatch.setenv("XIAOMAN_V2", "1")
    from app.study.v2.routes import router as v2_router
    from app.study.plan.routes import router as plan_router
    from app.study.practice.routes import router as practice_router
    app = FastAPI()
    for router in (v2_router, plan_router, practice_router):
        app.include_router(router)
    with RawTestClient(app) as client:
        yield client


@pytest.fixture
def owner(auth):
    user_id = f"exam-{uuid4().hex}"
    return user_id, auth(user_id)


def get(api, owner, path):
    response = api.get(path, headers=owner[1])
    assert response.status_code == 200, response.text
    return response.json()["data"]


def post(api, owner, path, payload=None, status=200):
    response = api.post(path, headers=owner[1], json=payload)
    assert response.status_code == status, response.text
    return response.json().get("data")


def accept(api, owner, minutes=30):
    draft = post(api, owner, "/api/v2/outline/draft", {
        "goal_type": "exam", "title": "考 PMP", "daily_minutes": minutes, "materials": "none",
    })
    return post(api, owner, f"/api/v2/outline/{draft['id']}/accept")["outline"]


def tasks(api, owner):
    return {task["kind"]: task for task in get(api, owner, "/api/plan/today")["tasks"]}


def test_daily_exam_counts_by_intensity_and_only_ticks_exam(api, owner):
    accept(api, owner)
    plan = get(api, owner, "/api/plan/today")
    assert [task["kind"] for task in plan["tasks"]] == ["learn", "practice", "exam"]
    exam = post(api, owner, f"{BASE}/start")
    assert exam["type"] == "daily" and exam["lecture_no"] == 1 and exam["mistake_count"] == 0
    assert len(exam["questions"]) == scheduler.EXAM_COUNT[plan["intensity"]]
    assert all(set(question) == {"id", "stem", "options"} for question in exam["questions"])
    assert post(api, owner, f"{BASE}/start")["id"] == exam["id"]  # 同一天重复点是同一份卷子

    answers = {question["id"]: "A" for question in exam["questions"]}
    report = post(api, owner, f"{BASE}/{exam['id']}/submit", {"answers": answers})
    assert report["total"] == len(answers) and 0 <= report["score"] <= 100
    assert post(api, owner, f"{BASE}/{exam['id']}/submit", {"answers": answers}) == report  # 重复交卷不重算
    now = tasks(api, owner)
    assert now["exam"]["status"] == "done"
    assert now["practice"]["status"] == "todo" and now["learn"]["status"] == "todo"  # 考试不顺带勾掉练习


def test_next_day_exam_puts_yesterdays_mistakes_first(api, owner):
    accept(api, owner)
    exam = post(api, owner, f"{BASE}/start")
    answers = {question["id"]: "A" for question in exam["questions"]}  # 模拟题正确答案是 B
    report = post(api, owner, f"{BASE}/{exam['id']}/submit", {"answers": answers})
    wrong = report["total"] - report["correct"]
    assert wrong > 0
    learn = tasks(api, owner)["learn"]
    assert api.patch(f"/api/tasks/{learn['id']}", headers=owner[1], json={"status": "done"}).status_code == 200
    post(api, owner, "/api/demo/clock", {"days": 1})

    today = tasks(api, owner)
    assert today["learn"]["ref"]["lecture_no"] == 2 and today["exam"]["ref"]["lecture_no"] == 2
    assert len(today["exam"]["ref"]["mistake_ids"]) == wrong
    second = post(api, owner, f"{BASE}/start")
    size = scheduler.EXAM_COUNT[get(api, owner, "/api/plan/today")["intensity"]]
    assert second["mistake_count"] == min(wrong, size)
    assert [q["id"] for q in second["questions"][: second["mistake_count"]]] == today["exam"]["ref"]["mistake_ids"][:size]


def test_stage_day_exam_is_the_stage_assessment(api, owner):
    outline = accept(api, owner)
    stage = outline["stages"][0]["unit_nos"]
    checkpoints = get(api, owner, "/api/v2/outline/current")["outline"]["checkpoints"]
    assert [c["status"] for c in checkpoints] == ["upcoming"] * len(outline["stages"])
    assert checkpoints[0]["after_unit"] == stage[-1]
    for _ in range(len(stage)):
        learn = tasks(api, owner).get("learn")
        assert api.patch(f"/api/tasks/{learn['id']}", headers=owner[1], json={"status": "done"}).status_code == 200
        if learn["ref"]["lecture_no"] == stage[-1]:
            break
        post(api, owner, "/api/demo/clock", {"days": 1})
    quiz = post(api, owner, f"{BASE}/start")
    assert quiz["type"] == "stage" and len(quiz["questions"]) == 10
    answers = {question["id"]: "B" for question in quiz["questions"]}
    assert get(api, owner, "/api/v2/outline/current")["outline"]["checkpoints"][0]["status"] == "ready"
    report = post(api, owner, f"/api/v2/assessment/{quiz['id']}/submit", {"answers": answers})
    first = get(api, owner, "/api/v2/outline/current")["outline"]["checkpoints"][0]
    assert first["status"] == "done" and first["score"] == report["score"]
    now = tasks(api, owner)
    assert now["exam"]["status"] == "done" and now["practice"]["status"] == "todo"


def test_exam_isolated_between_users(api, owner, auth):
    accept(api, owner)
    exam = post(api, owner, f"{BASE}/start")
    other = ("exam-other-" + uuid4().hex,)
    headers = auth(other[0])
    answers = {exam["questions"][0]["id"]: "A"}
    assert api.post(f"{BASE}/{exam['id']}/submit", headers=headers, json={"answers": answers}).status_code == 404
    assert api.post(f"{BASE}/start", headers=headers).status_code == 409  # 别人没目标、没考试


def test_exam_routes_absent_when_v2_off(monkeypatch, auth):
    monkeypatch.delenv("XIAOMAN_V2", raising=False)
    import importlib
    import app.study.router as routes
    importlib.reload(routes)
    app = FastAPI()
    app.include_router(routes.router)
    with RawTestClient(app) as client:
        assert client.post(BASE + "/start", headers=auth("exam-off-" + uuid4().hex)).status_code == 404


def test_learn_next_counts_progress_for_tomorrow(api, owner):
    accept(api, owner)
    learn = tasks(api, owner)["learn"]
    assert api.patch(f"/api/tasks/{learn['id']}", headers=owner[1], json={"status": "done"}).status_code == 200
    assert get(api, owner, "/api/v2/outline/current")["outline"]["learned_up_to"] == 1
    assert post(api, owner, "/api/v2/progress", {"unit_no": 3}, status=422) is None  # 不能跳讲
    assert post(api, owner, "/api/v2/progress", {"unit_no": 2}) == {"learned_up_to": 2}
    assert post(api, owner, "/api/v2/progress", {"unit_no": 2}) == {"learned_up_to": 2}  # 重复提交不变
    post(api, owner, "/api/demo/clock", {"days": 1})
    tomorrow = tasks(api, owner)
    assert tomorrow["learn"]["ref"]["lecture_no"] == 3 and tomorrow["exam"]["ref"]["lecture_no"] == 3


def test_today_summary_counts_and_keeps_total_days(api, owner):
    accept(api, owner)
    assert get(api, owner, "/api/v2/today/summary")["all_done"] is False
    today = tasks(api, owner)
    for kind in ("learn", "practice"):
        assert api.patch(f"/api/tasks/{today[kind]['id']}", headers=owner[1], json={"status": "done"}).status_code == 200
    exam = post(api, owner, f"{BASE}/start")
    post(api, owner, f"{BASE}/{exam['id']}/submit", {"answers": {q["id"]: "B" for q in exam["questions"]}})
    post(api, owner, "/api/v2/progress", {"unit_no": 2})
    data = get(api, owner, "/api/v2/today/summary")
    assert data["all_done"] is True
    assert [item["no"] for item in data["lectures"]] == [1, 2] and all(item["title"] for item in data["lectures"])
    assert data["exam"]["kind"] == "daily" and data["exam"]["total"] == len(exam["questions"])
    assert data["practice"]["total"] == 0  # 考试题不算练一练
    assert data["total_days"] == 1 and data["lines"][-1].startswith("累计学了 1 天")
    assert all("连续" not in line for line in data["lines"])

    post(api, owner, "/api/demo/clock", {"days": 2})  # 隔一天没学
    first = tasks(api, owner)["learn"]
    assert api.patch(f"/api/tasks/{first['id']}", headers=owner[1], json={"status": "done"}).status_code == 200
    again = get(api, owner, "/api/v2/today/summary")
    assert again["total_days"] == 2 and again["all_done"] is False  # 断了不清零
    assert [item["no"] for item in again["lectures"]] == [3]


def test_mistake_book_groups_and_drops_after_correct_redo(api, owner, auth):
    accept(api, owner)
    exam = post(api, owner, f"{BASE}/start")
    post(api, owner, f"{BASE}/{exam['id']}/submit", {"answers": {q["id"]: "A" for q in exam["questions"]}})
    data = get(api, owner, "/api/v2/mistakes")
    assert data["count"] == len(exam["questions"])
    group = data["groups"][0]
    assert group["lecture_no"] == 1 and group["title"]
    item = group["items"][0]
    assert item["your_answer"] == "A" and item["your_answer_text"] and item["answer_text"]
    assert get(api, ("x",) + (auth("exam-other-" + uuid4().hex),), "/api/v2/mistakes")["count"] == 0  # 别人看不到

    quiz = post(api, owner, "/api/quizzes", {"mode": "review", "question_ids": [item["question_id"]], "count": 1})
    question = quiz["questions"][0]
    result = post(api, owner, "/api/attempts", {"quiz_id": quiz["quiz_id"], "question_id": question["id"], "answer": "B"})
    assert result["correct"] is True
    after = get(api, owner, "/api/v2/mistakes")
    assert after["count"] == data["count"] - 1
    assert item["question_id"] not in {i["question_id"] for g in after["groups"] for i in g["items"]}
