"""看板真实聚合、所有权、反馈、用量；不更改其他线的算法。"""
import json
import uuid
from datetime import date

import pytest

from app.data_access.session import SessionLocal
from app.study.common.db import ensure_schema
from app.study.common.models import (
    Attempt, BadCase, Chapter, Course, Goal, KnowledgePoint, PlanTask, Question, StudyEvent, StudyMessage,
)
from app.study.dashboard.service import snapshot
from app.study.dashboard.telemetry import capture_feedback, record_call, usage_summary


def insert(*rows):
    ensure_schema()
    with SessionLocal() as session:
        session.add_all(rows)
        session.commit()


@pytest.fixture
def person():
    return "board-" + uuid.uuid4().hex


def test_empty_read_does_not_seed(person):
    board = snapshot(person, today=date(2026, 11, 6))
    assert [board[k] for k in ("studied_days", "attempt_count", "mistakes_due", "goal_progress")] == [0, 0, 0, 0]
    assert not board["mock"] and board["lectures"] == []


def test_week_boundaries_and_latest_attempt(person):
    insert(Question(id=person+"q", user_id=person, lecture_id="lecture"),
           Attempt(id=person+"1", user_id=person, question_id=person+"q", correct=0, created_at="2026-11-01T15:59:59Z"),
           Attempt(id=person+"2", user_id=person, question_id=person+"q", correct=0, created_at="2026-11-01T16:00:00Z"),
           Attempt(id=person+"3", user_id=person, question_id=person+"q", correct=1, created_at="2026-11-06T01:00:00Z"),
           Attempt(id=person+"4", user_id=person, question_id=person+"q", correct=0, created_at="2026-11-07T01:00:00Z"),
           Attempt(id=person+"5", user_id="someone-else", question_id=person+"q", correct=0, created_at="2026-11-06T02:00:00Z"))
    before = snapshot(person, today=date(2026, 11, 5))
    after = snapshot(person, today=date(2026, 11, 6))
    assert before["mistakes_due"] == 1
    assert after["period"]["start"] == "2026-11-02"
    assert after["studied_days"] == 2 and after["attempt_count"] == 2
    assert after["mistakes_due"] == 0
    with SessionLocal() as session:
        assert session.get(Attempt, person+"2").correct == 0


def test_task_days_mastery_and_goal_progress(person):
    insert(Goal(id=person+"g", user_id=person, title="公开课", lecture_count=2),
           Course(id=person+"c", user_id=person, goal_id=person+"g"),
           Chapter(id=person+"ch", user_id=person, course_id=person+"c", lecture_id="lecture", title="第1讲"),
           KnowledgePoint(id=person+"kp1", user_id=person, lecture_id="lecture", mastery=40),
           KnowledgePoint(id=person+"kp2", user_id=person, lecture_id="lecture", mastery=80),
           KnowledgePoint(id=person+"other", user_id="someone-else", lecture_id="lecture", mastery=100),
           PlanTask(id=person+"t", user_id=person, kind="learn", day="2026-11-03", status="done", ref_json='{"lecture_id":"lecture"}'),
           PlanTask(id=person+"t2", user_id=person, kind="learn", day="2026-11-03", status="done", ref_json='{"lecture_id":"lecture"}'))
    before = snapshot(person, today=date(2026, 11, 6))
    assert before["studied_days"] == 1 and before["goal_progress"] == 0.5
    assert before["lectures"][0]["mastery"] == 60
    with SessionLocal() as session:
        session.get(KnowledgePoint, person+"kp1").mastery = 80
        session.commit()
    assert snapshot(person, today=date(2026, 11, 6))["lectures"][0]["mastery"] == 80


def test_opening_and_undo_do_not_erase_learning(person):
    insert(StudyEvent(id=person+"seed", user_id=person, name="foundation_seed", at="2026-11-06T00:00:00Z"),
           StudyEvent(id=person+"done", user_id=person, name="task_status", at="2026-11-05T00:00:00Z", props_json='{"task_id":"task", "status":"done"}'),
           StudyEvent(id=person+"undo", user_id=person, name="task_status", at="2026-11-05T01:00:00Z", props_json='{"task_id":"task", "status":"todo"}'))
    board = snapshot(person, today=date(2026, 11, 6))
    assert board["mock"] and board["studied_days"] == 1


def test_usage_uses_reported_tokens_and_does_not_fabricate_price(person):
    for model, estimated in [("deepseek-flash", False), ("unknown-model", False), ("deepseek-flash", True)]:
        record_call(user_id=person, capability="问答", prompt_name="qa.answer", prompt_version="v1", model=model,
                    prompt_tokens=1000000, completion_tokens=1000000, latency_ms=10, ok=True, estimated=estimated)
    data = usage_summary(person)
    assert data["by_capability"]["问答"]["calls"] == 3
    assert data["totals_by_currency"] == {"CNY": 10.0}
    assert sum(g["unpriced_calls"] for g in data["groups"]) == 2
    assert usage_summary(person+"other")["groups"] == []
    with pytest.raises(ValueError):
        record_call(user_id=person, capability="qa", prompt_name="q", prompt_version="v1", model="x", prompt_tokens=-1, completion_tokens=2, latency_ms=0, ok=False)


def test_feedback_ownership_idempotence_and_provenance(person):
    insert(StudyMessage(id=person+"m", user_id=person, content="原回答", refs_json=json.dumps({"model":"actual-model", "prompt_version":"qa.answer@v2", "input":{"question":"公开样例问题"}})),
           Question(id=person+"q", user_id=person, stem="公开样例题"))
    case = capture_feedback(person, target_type="message", target_id=person+"m", reason="出处不对")
    assert case == capture_feedback(person, target_type="message", target_id=person+"m", reason="再次点击")
    assert capture_feedback(person+"other", target_type="message", target_id=person+"m", reason="") is None
    with SessionLocal() as session:
        record = session.get(BadCase, case)
        assert record.actual_output == "原回答" and record.model == "actual-model" and record.prompt_version == "qa.answer@v2"
        assert "公开样例问题" in record.input_json


def test_http_routes_reject_forged_owner(client, auth, person):
    board = client.get("/api/dashboard", headers=auth(person)).json()
    assert board["data"]["studied_days"] == 0
    assert client.get("/api/dashboard?range=all", headers=auth(person)).status_code == 422
    assert client.get("/api/dashboard/summary", headers=auth(person)).json()["data"]["card"]["type"] == "dashboard"
    insert(Question(id=person+"q", user_id=person, stem="公开题目"))
    body = {"target_type":"question", "target_id":person+"q", "reason":"题有误", "user_id":person}
    assert client.post("/api/study/feedback", json=body, headers=auth(person+"other")).status_code == 404
    assert client.post("/api/study/feedback", json=body, headers=auth(person)).status_code == 200


def test_gateway_attempts_are_attributed_to_actual_models(monkeypatch, person):
    from pydantic import BaseModel
    from app.gateway.config import ModelSpec
    from app.gateway.core import Result
    from app.study.dashboard.telemetry import tracked_json

    class Answer(BaseModel):
        verdict: str

    result=Result(content='```json\n{"verdict":"pass"}\n```', spec=ModelSpec(id="backup", model="deepseek-v4-pro"), attempts=[
        {"model":"deepseek-flash","prompt_tokens":None,"completion_tokens":None,"latency_ms":10,"ok":False,"error":"timeout"},
        {"model":"deepseek-v4-pro","prompt_tokens":100,"completion_tokens":20,"latency_ms":30,"ok":True,"error":""},
    ])
    monkeypatch.setattr("app.study.dashboard.telemetry.core.complete", lambda *args, **kwargs:result)
    assert tracked_json(user_id=person, capability="评测复核",prompt_name="dashboard.eval",prompt_version="v1",payload={"public_sample":True},response_model=Answer).verdict == "pass"
    groups=usage_summary(person)["groups"]
    assert len(groups) == 2
    assert next(g for g in groups if g["model"] == "deepseek-flash")["estimated_calls"] == 1
    with SessionLocal() as session:
        from sqlalchemy import select
        case=session.scalar(select(BadCase).where(BadCase.user_id == person))
        assert case.model == "deepseek-flash" and case.prompt_version == "dashboard.eval@v1"


def test_plan_progress_and_demo_clock_share_the_same_day(monkeypatch, person):
    from app.study.plan import demo, service
    monkeypatch.setenv("XIAOMAN_DEMO_CLOCK", "1")
    monkeypatch.setattr(demo, "real_today", lambda: date(2026, 11, 6))
    service.plan_today(person)
    first = snapshot(person)
    assert first["plan_progress"] is not None
    assert first["goal_progress"] == first["plan_progress"]["goal_progress"]
    demo.advance(person, 1)
    plan = service.plan_today(person)
    task = plan["tasks"][0]
    service.patch_task(person, task["id"], status="done")
    after = snapshot(person)
    assert after["period"]["end"] == "2026-11-07"
    assert "演示用" in after["label"]
    assert after["studied_days"] >= 1
    assert after["goal_progress"] == after["plan_progress"]["goal_progress"]
