"""T04 通过 HTTP 复用大纲、练习、计划和看板，并检查数据隔离。"""
import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from app.data_access.session import SessionLocal
from app.study.common.models import Attempt, Question, StudyEvent
from app.study.v2 import assessment
from app.study.v2.models import GoalOutline
from tests.conftest import RawTestClient

BASE = "/api/v2/assessment"


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("XIAOMAN_DEMO_CLOCK", "1")
    from app.study.v2.routes import router as v2_router
    from app.study.plan.routes import router as plan_router
    from app.study.dashboard.routes import router as dashboard_router

    app = FastAPI()
    for router in (v2_router, plan_router, dashboard_router):
        app.include_router(router)
    with RawTestClient(app) as client:
        yield client


@pytest.fixture
def owner(auth):
    user_id = f"assessment-{uuid4().hex}"
    return user_id, auth(user_id)


def get(api, owner, path):
    response = api.get(path, headers=owner[1])
    assert response.status_code == 200, response.text
    return response.json()["data"]


def post(api, owner, path, payload=None):
    response = api.post(path, headers=owner[1], json=payload)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def accept_outline(api, owner, minutes=15):
    draft = post(api, owner, "/api/v2/outline/draft", {
        "goal_type": "exam", "title": "考 PMP", "daily_minutes": minutes, "materials": "none",
    })
    return post(api, owner, f"/api/v2/outline/{draft['id']}/accept")["outline"]


def practice_tasks(api, owner):
    return [task for task in get(api, owner, "/api/plan/today")["tasks"] if task["kind"] == "practice"]


def learn_four_units(api, owner):
    outline = accept_outline(api, owner)
    assert len(outline["units"]) == 4
    learned = set()
    for _ in range(4):
        tasks = get(api, owner, "/api/plan/today")["tasks"]
        for task in tasks:
            if task["kind"] != "learn" or task["status"] != "todo":
                continue
            response = api.patch(f"/api/tasks/{task['id']}", headers=owner[1], json={"status": "done"})
            assert response.status_code == 200, response.text
            learned.add(task["ref"]["lecture_no"])
        post(api, owner, "/api/demo/clock", {"days": 1})
        if learned == {1, 2, 3, 4}:
            break
    assert learned == {1, 2, 3, 4}
    assert len(practice_tasks(api, owner)) == 3


def grouped_questions(user_id, quiz):
    with SessionLocal() as session:
        lectures = dict(session.execute(select(Question.id, Question.lecture_id).where(
            Question.user_id == user_id, Question.id.in_([q["id"] for q in quiz["questions"]]),
        )).all())
    return {
        number: [q["id"] for q in quiz["questions"] if lectures[q["id"]] == f"lec-{number}"]
        for number in quiz["stage"]["unit_nos"]
    }


def attempt_count(user_id):
    with SessionLocal() as session:
        return session.scalar(select(func.count()).select_from(Attempt).where(Attempt.user_id == user_id))


def test_stage_done_report_mistakes_and_auto_completion(api, owner):
    learn_four_units(api, owner)
    due = get(api, owner, f"{BASE}/due")
    assert due["due"] and due["reason"] == "stage_done" and due["open_id"] is None
    before = practice_tasks(api, owner)
    quiz = post(api, owner, f"{BASE}/start")
    assert quiz["label"] == "模拟" and quiz["mock"]
    assert len(quiz["questions"]) == 10
    assert all(set(question) == {"id", "stem", "options"} for question in quiz["questions"])
    assert get(api, owner, f"{BASE}/due")["open_id"] == quiz["id"]
    assert post(api, owner, f"{BASE}/start") == quiz
    by_unit = grouped_questions(owner[0], quiz)
    assert [len(ids) for ids in by_unit.values()] == [3, 3, 2, 2]

    wrong_id = by_unit[2][0]
    answers = {**dict.fromkeys(by_unit[1], "B"), wrong_id: "A"}
    path = f"{BASE}/{quiz['id']}/submit"
    report = post(api, owner, path, {"answers": answers})
    assert report["score"] == 75
    assert [(unit["no"], unit["correct"], unit["total"]) for unit in report["units"]] == [
        (1, 3, 3), (2, 0, 1), (3, 0, 0), (4, 0, 0),
    ]
    assert report["weak_unit_nos"] == [2] and report["next_stage"] is None
    assert report["summary"] == "这一阶段做了 4 题，对了 3 题。第 2 单元再看一眼会更稳。"
    after = practice_tasks(api, owner)
    assert [task["id"] for task in after] == [task["id"] for task in before]
    assert [task["status"] for task in after] == ["done", "todo", "todo"]
    assert post(api, owner, path, {"answers": {}}) == report
    assert attempt_count(owner[0]) == 4
    assert not get(api, owner, f"{BASE}/due")["due"]
    with SessionLocal() as session:
        groups = session.scalar(select(func.count()).select_from(StudyEvent).where(
            StudyEvent.user_id == owner[0], StudyEvent.name == "practice_quiz_created",
        ))
        assert groups == 4

    post(api, owner, "/api/demo/clock", {"days": 1})
    tasks = get(api, owner, "/api/plan/today")["tasks"]
    assert any(task["kind"] == "repair" and wrong_id in task["ref"].get("question_ids", []) for task in tasks)
    # 作答存真实日期，演示时间可能已跨周，切回后再验看板。
    post(api, owner, "/api/demo/clock/reset")
    assert get(api, owner, "/api/dashboard")["attempt_count"] == 4


def test_fallback_marks_only_first_pending_practice(api, owner):
    learn_four_units(api, owner)
    before = practice_tasks(api, owner)
    done = api.patch(f"/api/tasks/{before[0]['id']}", headers=owner[1], json={"status": "done"})
    assert done.status_code == 200
    quiz = post(api, owner, f"{BASE}/start")
    lecture_ids = {task["ref"]["lecture_id"] for task in before}
    outside_plan = next(ids[0] for no, ids in grouped_questions(owner[0], quiz).items() if f"lec-{no}" not in lecture_ids)
    path = f"{BASE}/{quiz['id']}/submit"
    report = post(api, owner, path, {"answers": {outside_plan: "B"}})
    assert report["score"] == 100
    assert post(api, owner, path, {"answers": {outside_plan: "A"}}) == report
    after = practice_tasks(api, owner)
    assert [task["id"] for task in after] == [task["id"] for task in before]
    assert [task["status"] for task in after] == ["done", "done", "todo"]
    assert attempt_count(owner[0]) == 1


def test_seven_days_and_next_stage_use_demo_clock(api, owner):
    outline = accept_outline(api, owner, minutes=30)
    assert len(outline["units"]) == 5
    post(api, owner, "/api/demo/clock", {"days": 6})
    assert not get(api, owner, f"{BASE}/due")["due"]
    assert api.post(f"{BASE}/start", headers=owner[1]).status_code == 409
    clock = post(api, owner, "/api/demo/clock", {"days": 1})
    due = get(api, owner, f"{BASE}/due")
    assert due["due"] and due["reason"] == "seven_days" and due["stage"]["no"] == 1
    quiz = post(api, owner, f"{BASE}/start")
    assert not practice_tasks(api, owner)
    before = get(api, owner, "/api/plan/today")["tasks"]
    report = post(api, owner, f"{BASE}/{quiz['id']}/submit", {"answers": {quiz["questions"][0]["id"]: "B"}})
    assert report["next_stage"]["no"] == 2
    assert get(api, owner, "/api/plan/today")["tasks"] == before
    with SessionLocal() as session:
        stages = json.loads(session.get(GoalOutline, outline["id"]).stages_json)
        assert stages[1]["started_at"] == clock["today"]
    post(api, owner, "/api/demo/clock", {"days": 6})
    assert not get(api, owner, f"{BASE}/due")["due"]
    post(api, owner, "/api/demo/clock", {"days": 1})
    assert get(api, owner, f"{BASE}/due")["reason"] == "seven_days"
    next_quiz = post(api, owner, f"{BASE}/start")
    assert next_quiz["id"] != quiz["id"] and next_quiz["stage"]["no"] == 2
    assert len(next_quiz["questions"]) == 10


def test_isolation_and_invalid_answers_are_rejected_before_grading(api, owner, auth):
    accept_outline(api, owner)
    post(api, owner, "/api/demo/clock", {"days": 7})
    quiz = post(api, owner, f"{BASE}/start")
    qid = quiz["questions"][0]["id"]
    path = f"{BASE}/{quiz['id']}/submit"
    other_id = f"assessment-{uuid4().hex}"
    other = (other_id, auth(other_id))
    assert get(api, other, f"{BASE}/due") == {"due": False, "stage": None, "reason": None, "open_id": None}
    assert api.post(path, headers=other[1], json={"answers": {qid: "B"}}).status_code == 404
    assert api.get(f"{BASE}/due").status_code == 401
    for answers in ({}, {qid: "B", "unknown": "A"}, {qid: "D"}, {qid: "invalid"}):
        assert api.post(path, headers=owner[1], json={"answers": answers}).status_code == 422
    assert attempt_count(owner[0]) == attempt_count(other_id) == 0
    assert get(api, owner, f"{BASE}/due")["open_id"] == quiz["id"]


def test_partial_failure_retries_original_submission(api, owner, monkeypatch):
    accept_outline(api, owner)
    post(api, owner, "/api/demo/clock", {"days": 7})
    quiz = post(api, owner, f"{BASE}/start")
    first, second = [q["id"] for q in quiz["questions"][:2]]
    submit = assessment.practice_service.submit

    def fail_second(user_id, body):
        if body.question_id == second:
            raise RuntimeError("测试中断逐题判分")
        return submit(user_id, body)

    path = f"{BASE}/{quiz['id']}/submit"
    with monkeypatch.context() as patch:
        patch.setattr(assessment.practice_service, "submit", fail_second)
        with pytest.raises(RuntimeError, match="测试中断"):
            api.post(path, headers=owner[1], json={"answers": {first: "B", second: "B"}})
    assert attempt_count(owner[0]) == 1
    report = post(api, owner, path, {"answers": {first: "A"}})
    assert report["score"] == 100
    assert attempt_count(owner[0]) == 2


def test_concurrent_starts_and_submits_share_one_assessment(api, owner):
    accept_outline(api, owner)
    post(api, owner, "/api/demo/clock", {"days": 7})
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.map(lambda _: post(api, owner, f"{BASE}/start"), range(2))
        assert first == second
        path = f"{BASE}/{first['id']}/submit"
        answers = {first["questions"][0]["id"]: "B"}
        reports = list(pool.map(lambda _: post(api, owner, path, {"answers": answers}), range(2)))
    assert reports[0] == reports[1]
    assert attempt_count(owner[0]) == 1


def test_disabled_switch_keeps_assessment_routes_unregistered(monkeypatch, owner):
    from importlib import reload
    from app.study import router as study_router

    monkeypatch.delenv("XIAOMAN_V2", raising=False)
    app = FastAPI()
    app.include_router(reload(study_router).router)
    with RawTestClient(app) as client:
        assert client.get(f"{BASE}/due", headers=owner[1]).status_code == 404
        assert client.post(f"{BASE}/start", headers=owner[1]).status_code == 404
        assert client.post(f"{BASE}/unknown/submit", headers=owner[1], json={"answers": {}}).status_code == 404
        assert client.get("/api/plan/today", headers=owner[1]).status_code == 200
