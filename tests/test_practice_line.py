"""练习闭环与真实网关输出校验的离线回归，不调用付费模型。"""
import json
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.study.practice import capabilities, service
from app.study.practice.schemas import GeneratedQuestion


def quiz(client, auth, uid, **body):
    response = client.post("/api/quizzes", json={"lecture_id": "lec-6", **body}, headers=auth(uid))
    assert response.status_code == 200, response.text
    return response.json()["data"]


def answer(client, auth, uid, group, index, choice):
    response = client.post("/api/attempts", json={"quiz_id": group["quiz_id"],
        "question_id": group["questions"][index]["id"], "answer": choice}, headers=auth(uid))
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_five_questions_answer_hidden_and_reuse(client, auth):
    first = quiz(client, auth, "p-five")
    assert len(first["questions"]) == 5 and first["mock"]
    assert all("answer" not in q and "analysis" not in q and "quote" not in q["source"] for q in first["questions"])
    second = quiz(client, auth, "p-five")
    assert second["reused"] and second["quiz_id"] != first["quiz_id"]
    assert [q["id"] for q in first["questions"]] == [q["id"] for q in second["questions"]]


def test_three_right_two_wrong_resume_and_idempotence(client, auth):
    uid = "p-flow"
    group = quiz(client, auth, uid)
    first = answer(client, auth, uid, group, 0, "A")
    repeated = answer(client, auth, uid, group, 0, "B")
    assert first["attempt_id"] == repeated["attempt_id"] and repeated["your_answer"] == "A"
    restored = client.get(f"/api/quizzes/{group['quiz_id']}", headers=auth(uid)).json()["data"]
    assert len(restored["results"]) == 1 and not restored["completed"]
    for i, choice in enumerate(["A", "B", "B", "B"], 1):
        last = answer(client, auth, uid, group, i, choice)
    assert last["quiz_completed"]
    wrong = client.get("/api/mistakes", headers=auth(uid)).json()["data"]["items"]
    assert len(wrong) == 2
    stats = client.get("/api/practice/stats", headers=auth(uid)).json()["data"]
    assert stats["week_attempt_count"] == 5 and stats["mistakes_pending"] == 2


def test_wrong_review_changes_mastery_and_keeps_attempts(client, auth, monkeypatch):
    uid = "p-review"
    group = quiz(client, auth, uid, count=1)
    old = answer(client, auth, uid, group, 0, "A")
    tomorrow = service.today() + timedelta(days=1)
    assert old["next_review_on"] == tomorrow.isoformat()
    due = client.get(f"/api/practice/review-due?on={tomorrow}", headers=auth(uid)).json()["data"]
    assert len(due["mistakes"]) == 1
    revised = quiz(client, auth, uid, mode="review", question_ids=[group["questions"][0]["id"]])
    assert len(revised["questions"]) == 1
    assert revised["questions"][0]["stem"] != group["questions"][0]["stem"]
    new = answer(client, auth, uid, revised, 0, "B")
    assert new["mastery"] > old["mastery"]
    assert client.get("/api/mistakes", headers=auth(uid)).json()["data"]["items"] == []
    assert client.get("/api/practice/stats", headers=auth(uid)).json()["data"]["week_attempt_count"] == 2


def test_review_wrong_still_completes(client, auth):
    uid = "p-review-wrong"
    group = quiz(client, auth, uid, count=1)
    answer(client, auth, uid, group, 0, "A")
    revised = quiz(client, auth, uid, mode="review")
    result = answer(client, auth, uid, revised, 0, "A")
    assert result["quiz_completed"] and not result["correct"]
    wrong = client.get("/api/mistakes", headers=auth(uid)).json()["data"]["items"]
    assert len(wrong) == 1


def test_multiple_mistakes_reviewed_in_one_card(client, auth):
    uid = "p-multiple-review"
    group = quiz(client, auth, uid, count=2)
    answer(client, auth, uid, group, 0, "A")
    answer(client, auth, uid, group, 1, "A")
    revised = quiz(client, auth, uid, mode="review", count=2)
    assert len(revised["questions"]) == 2
    answer(client, auth, uid, revised, 0, "B")
    last = answer(client, auth, uid, revised, 1, "B")
    assert last["quiz_completed"]
    assert client.get("/api/mistakes", headers=auth(uid)).json()["data"]["items"] == []


def test_completed_task_stays_done_even_wrong(client, auth):
    uid = "p-task"
    plan = client.get("/api/plan/today", headers=auth(uid)).json()["data"]
    task = next(t for t in plan["tasks"] if t["kind"] == "practice")
    group = quiz(client, auth, uid, count=1, task_id=task["id"])
    result = answer(client, auth, uid, group, 0, "A")
    assert result["completed_task_id"] == task["id"]
    now = client.get("/api/plan/today", headers=auth(uid)).json()["data"]
    assert len(now["tasks"]) == 3
    assert next(t for t in now["tasks"] if t["id"] == task["id"])["status"] == "done"
    again = quiz(client, auth, uid, count=1, task_id=task["id"])
    answer(client, auth, uid, again, 0, "A")
    assert next(t for t in client.get("/api/plan/today", headers=auth(uid)).json()["data"]["tasks"] if t["id"] == task["id"])["status"] == "done"


def test_cross_account_and_wrong_group_rejected(client, auth):
    group = quiz(client, auth, "p-owner", count=1)
    qid = group["questions"][0]["id"]
    for path, body in [("/api/attempts", {"question_id": qid, "answer": "B"}),
                       ("/api/practice/reports", {"question_id": qid}),
                       ("/api/quizzes", {"mode": "review", "question_ids": [qid]})]:
        assert client.post(path, json=body, headers=auth("p-stranger")).status_code == 404
    assert client.get(f"/api/quizzes/{group['quiz_id']}", headers=auth("p-stranger")).status_code == 404
    other = quiz(client, auth, "p-owner", count=2)
    assert client.post("/api/attempts", json={"quiz_id": group["quiz_id"], "question_id": other["questions"][0]["id"], "answer": "B"}, headers=auth("p-owner")).status_code == 404


def test_feedback_enters_bad_case(client, auth):
    uid = "p-feedback"
    group = quiz(client, auth, uid, count=1)
    r = client.post("/api/practice/reports", json={"question_id": group["questions"][0]["id"], "reason": "选项有歧义", "category": "ambiguous"}, headers=auth(uid))
    assert r.status_code == 200 and r.json()["data"]["bad_case_id"]
    cases = client.get("/api/study/bad-cases", headers=auth(uid)).json()["data"]["items"]
    assert cases[-1]["source"] == "question_feedback"


def test_invalid_input_and_unknown_lecture(client, auth):
    headers = auth("p-invalid")
    assert client.post("/api/quizzes", json={"count": 16}, headers=headers).status_code == 422
    assert client.post("/api/quizzes", json={"lecture_id": "missing"}, headers=headers).status_code == 422
    assert client.post("/api/attempts", json={"question_id": "x", "answer": "E"}, headers=headers).status_code == 422


def test_schedule_uses_unweighted_accuracy_and_retains_intervals():
    day = date(2026, 11, 5)
    recent_right = service.mastery_schedule([False, True], {}, True, day)
    recent_wrong = service.mastery_schedule([True, False], {}, False, day)
    assert recent_right["mastery"] == recent_wrong["mastery"] == 50
    second = service.mastery_schedule([True, True], recent_right, True, day)
    assert second["interval"] == 6
    failed = service.mastery_schedule([True, False], second, False, day)
    assert failed["interval"] == 1 and failed["repetitions"] == 0


def generated_question():
    return {"stem": "根据原文，每天最多安排几件事？", "options": [{"id": "A", "text": "三件"}, {"id": "B", "text": "五件"}],
            "answer": "A", "analysis": "原文要求每天最多三件事。", "source": {"page": 1, "quote": "每天最多三件事"},
            "difficulty": "easy", "knowledge_point": "三件事"}


@pytest.mark.parametrize("failure", ["quote", "answer", "duplicate_check"])
def test_live_generation_rejects_false_quote_or_blind_answer(uid, monkeypatch, failure):
    from app.study.common.db import ensure_schema
    ensure_schema()
    monkeypatch.setattr(capabilities, "has_llm", lambda *a, **k: True)
    question = generated_question()
    if failure == "quote": question["source"]["quote"] = "这是编造的原句"
    calls = []
    def fake(system, user, **kwargs):
        calls.append(json.loads(user.split("\n", 1)[1].rsplit("\n", 1)[0]))
        if "独立" in system:
            answers = [{"index": 0, "answer": "B" if failure == "answer" else "A"}]
            if failure == "duplicate_check": answers *= 2
            return {"answers": answers}
        return {"questions": [question]}
    monkeypatch.setattr(capabilities, "chat_json", fake)
    with pytest.raises(capabilities.PracticeError):
        capabilities.generate(uid, "lecture", [{"page": 1, "text": "每天最多三件事。"}], 1, "easy")
    if len(calls) == 2:
        assert "answer" not in json.dumps(calls[1]["questions"]) and "analysis" not in json.dumps(calls[1]["questions"])


def test_live_generation_schema_repair_and_usage(uid, monkeypatch):
    from app.study.common.db import ensure_schema
    from app.data_access.session import SessionLocal
    from app.study.common.models import LlmCall
    ensure_schema()
    monkeypatch.setattr(capabilities, "has_llm", lambda *a, **k: True)
    calls = []
    def fake(system, user, **kwargs):
        calls.append(system)
        if "独立" in system: return {"answers": [{"index": 0, "answer": "A"}]}
        if len(calls) == 1: return {"wrong": True}
        return {"questions": [generated_question()]}
    monkeypatch.setattr(capabilities, "chat_json", fake)
    qs, mock = capabilities.generate(uid, "lecture", [{"page": 1, "text": "每天最多三件事。"}], 1, "easy")
    assert not mock and len(qs) == 1 and len(calls) == 3
    with SessionLocal() as session:
        records = session.scalars(select(LlmCall).where(LlmCall.user_id == uid)).all()
        assert len(records) == 3 and all(r.estimated == 1 for r in records)
        assert sum(r.ok for r in records) == 2


def test_generated_schema_rejects_duplicate_options():
    q = generated_question()
    q["options"][1]["text"] = "三件"
    with pytest.raises(ValueError): GeneratedQuestion.model_validate(q)
