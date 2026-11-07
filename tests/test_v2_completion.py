"""T06 从真实计划任务和阶段测验汇总完成卡。"""
import json
from uuid import uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.data_access.session import SessionLocal
from app.study.common.models import Attempt, Goal, PlanTask
from app.study.plan import demo
from app.study.v2.models import Assessment
from tests.conftest import RawTestClient

BASE = "/api/v2/completion"


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("XIAOMAN_DEMO_CLOCK", "1")
    from app.study.plan.routes import router as plan_router
    from app.study.v2.routes import router as v2_router

    app = FastAPI()
    app.include_router(plan_router)
    app.include_router(v2_router)
    with RawTestClient(app) as client:
        yield client


@pytest.fixture
def owner(auth):
    user_id = f"completion-{uuid4().hex}"
    return user_id, auth(user_id)


def call(api, owner, method, path, payload=None, code=200):
    response = api.request(method, path, headers=owner[1], json=payload)
    assert response.status_code == code
    return response.json().get("data")


def accept_outline(api, owner, minutes=30):
    draft = call(api, owner, "POST", "/api/v2/outline/draft", {
        "goal_type": "exam", "title": "考 PMP", "daily_minutes": minutes, "materials": "none",
    })
    return call(api, owner, "POST", f"/api/v2/outline/{draft['id']}/accept")["outline"]


def learn_all(api, owner, units):
    learned, days = set(), set()
    for _ in units:
        plan = call(api, owner, "GET", "/api/plan/today")
        for task in plan["tasks"]:
            if task["kind"] == "learn" and task["status"] == "todo":
                call(api, owner, "PATCH", f"/api/tasks/{task['id']}", {"status": "done"})
                learned.add(task["ref"]["lecture_no"])
                days.add(plan["date"])
        if learned == {unit["no"] for unit in units}:
            return days
        call(api, owner, "POST", "/api/demo/clock", {"days": 1})
    pytest.fail("计划未排完所有学习任务")


def take_assessment(api, owner, answers):
    quiz = call(api, owner, "POST", "/api/v2/assessment/start")
    assert quiz["mock"]
    payload = {question["id"]: answer for question, answer in zip(quiz["questions"], answers)}
    return call(api, owner, "POST", f"/api/v2/assessment/{quiz['id']}/submit", {"answers": payload})


def goal_state(user_id):
    with SessionLocal() as session:
        goal = session.scalar(select(Goal).where(Goal.user_id == user_id))
        return goal.status, json.loads(goal.summary_json)


def record_ids(user_id):
    with SessionLocal() as session:
        return tuple(set(session.scalars(select(model.id).where(model.user_id == user_id)))
                     for model in (Attempt, PlanTask, Assessment))


@pytest.mark.parametrize(("answers", "score", "suggest"), [
    ("BBBA", 75, True),
    ("BBBAA", 60, False),
    ("BBBBBBBAAA", 70, True),
])
def test_suggestion_and_card_use_latest_submitted_score(api, owner, answers, score, suggest):
    outline = accept_outline(api, owner)
    assert len(outline["units"]) == 5
    days = learn_all(api, owner, outline["units"])
    preview = call(api, owner, "GET", BASE)
    assert not preview["suggest"] and preview["card"]["last_score"] is None

    assert take_assessment(api, owner, "B")["score"] == 100
    assert take_assessment(api, owner, answers)["score"] == score
    days.add(demo.real_today().isoformat())
    with SessionLocal() as session:
        attempts = list(session.scalars(select(Attempt).where(Attempt.user_id == owner[0])))
        assert len(attempts) == len(answers) + 1
        assert sum(row.correct for row in attempts) == answers.count("B") + 1
    expected = {
        "days": len(days), "attempts": len(attempts), "first_score": 100, "last_score": score,
        "hardest_unit": outline["units"][4 if len(answers) == 10 else 3]["title"], "label": "模拟",
    }
    assert call(api, owner, "GET", BASE) == {
        "suggest": suggest, "reason": "all_done" if suggest else None, "card": expected, "done": False,
    }
    active_state = goal_state(owner[0])
    assert active_state[0] == "active"
    if not suggest:
        call(api, owner, "POST", BASE + "/confirm", {"reason": "suggested"}, code=409)
        assert goal_state(owner[0])[0] == "active"
        return

    records = record_ids(owner[0])
    assert call(api, owner, "POST", BASE + "/confirm", {"reason": "suggested"}) == expected
    status, summary = goal_state(owner[0])
    assert status == "done" and summary["v2"]["completed_at"] == demo.today(owner[0]).isoformat()
    assert call(api, owner, "GET", BASE) == {"suggest": False, "reason": None, "card": expected, "done": True}
    assert call(api, owner, "POST", BASE + "/confirm", {"reason": "suggested"}) == expected
    assert goal_state(owner[0]) == (status, summary)
    assert call(api, owner, "POST", BASE + "/undo") == {"done": False}
    assert goal_state(owner[0]) == active_state
    assert call(api, owner, "GET", BASE)["suggest"]
    assert record_ids(owner[0]) == records


def test_user_confirmation_stops_new_plans_and_undo_expires(api, owner):
    outline = accept_outline(api, owner, minutes=15)
    call(api, owner, "POST", "/api/demo/clock", {"days": 7})
    assert take_assessment(api, owner, "B")["score"] == 100
    assert not call(api, owner, "GET", BASE)["suggest"]  # 有成绩，单元还没勾完。
    call(api, owner, "POST", BASE + "/confirm", {"reason": "suggested"}, code=409)
    plan = call(api, owner, "GET", "/api/plan/today")
    assert plan["tasks"]
    call(api, owner, "POST", BASE + "/confirm", {"reason": "user_said"})
    assert call(api, owner, "GET", "/api/plan/today")["tasks"] == plan["tasks"]
    call(api, owner, "POST", BASE + "/undo")
    assert not call(api, owner, "GET", BASE)["done"]
    call(api, owner, "POST", "/api/demo/clock", {"days": 1})
    assert call(api, owner, "GET", "/api/plan/today")["tasks"]

    call(api, owner, "POST", BASE + "/confirm", {"reason": "user_said"})
    state = goal_state(owner[0])
    records = record_ids(owner[0])
    call(api, owner, "POST", "/api/demo/clock", {"days": 1})
    assert call(api, owner, "GET", "/api/plan/today")["tasks"] == []
    assert call(api, owner, "POST", BASE + "/confirm", {"reason": "user_said"})["last_score"] == 100
    assert goal_state(owner[0]) == state
    call(api, owner, "POST", BASE + "/undo", code=409)
    assert record_ids(owner[0]) == records
    assert goal_state(owner[0])[1]["v2"]["outline_id"] == outline["id"]


def test_user_isolation_and_empty_preview(api, owner, auth):
    accept_outline(api, owner)
    call(api, owner, "POST", "/api/v2/outline/draft", {
        "goal_type": "course", "title": "另一份草稿", "daily_minutes": 30, "materials": "none",
    })
    other_id = f"completion-{uuid4().hex}"
    other = (other_id, auth(other_id))
    assert call(api, other, "GET", BASE) == {"suggest": False, "reason": None, "card": None, "done": False}
    call(api, other, "POST", BASE + "/confirm", {"reason": "user_said"}, code=404)
    call(api, other, "POST", BASE + "/undo", code=404)
    accept_outline(api, other)
    empty = {"days": 0, "attempts": 0, "first_score": None, "last_score": None, "hardest_unit": None, "label": ""}
    assert call(api, other, "GET", BASE)["card"] == empty
    assert call(api, other, "POST", BASE + "/confirm", {"reason": "user_said"}) == empty
    assert call(api, other, "GET", BASE)["done"]
    assert call(api, owner, "GET", BASE) == {"suggest": False, "reason": None, "card": empty, "done": False}
    call(api, owner, "POST", BASE + "/undo", code=409)
    assert goal_state(other_id)[0] == "done"


def test_switch_off_keeps_completion_routes_unregistered(monkeypatch, owner):
    from importlib import reload
    from app.study import router as study_router

    monkeypatch.delenv("XIAOMAN_V2", raising=False)
    app = FastAPI()
    app.include_router(reload(study_router).router)
    with RawTestClient(app) as api:
        call(api, owner, "GET", BASE, code=404)
        call(api, owner, "POST", BASE + "/confirm", {"reason": "user_said"}, code=404)
        call(api, owner, "POST", BASE + "/undo", code=404)
        assert call(api, owner, "GET", "/api/plan/today")["tasks"]
