"""把握度、题目反馈与复习的同一规则闭环，不调用付费模型。"""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.study.common.models import Attempt, BadCase, StudyEvent
from app.study.practice import learning, service
from app.study.practice.reports import save_report
from tests.test_practice_interactions import create


def data(response):
    assert response.status_code == 200, response.text
    return response.json()["data"]


def submit(client, auth, uid, quiz, index=0, correct=True, confidence=""):
    return data(client.post("/api/attempts", headers=auth(uid), json={"quiz_id": quiz["quiz_id"],
        "question_id": quiz["questions"][index]["id"], "answer": "B" if correct else "A", "confidence": confidence}))


def summary(client, auth, uid):
    return data(client.get("/api/practice/stats?lecture_id=lec-6", headers=auth(uid)))


def library(client, auth, uid):
    return data(client.get("/api/practice/learning?lecture_id=lec-6", headers=auth(uid)))["items"]


def report(client, auth, uid, quiz, index=0, **extra):
    return client.post("/api/practice/reports", headers=auth(uid), json={"question_id": quiz["questions"][index]["id"],
        "quiz_id": quiz["quiz_id"], "category": "answer", "reason": "", **extra})


@pytest.mark.parametrize("correct,confidence,state,priority", [
    (True, "", "normal", False), (True, "low", "normal", False),
    (True, "medium", "normal", False), (True, "high", "normal", False),
    (False, "", "wrong", False), (False, "low", "wrong", False),
    (False, "medium", "wrong", False), (False, "high", "wrong", False),
])
def test_removed_confidence_ignored_and_submission_stays_immutable(client, auth, correct, confidence, state, priority):
    uid = f"matrix-{correct}-{confidence}"
    quiz = create(client, auth, uid, count=1)
    result = submit(client, auth, uid, quiz, correct=correct, confidence=confidence)
    assert (result["learning_state"], result["priority"]) == (state, priority)
    assert result["confidence"] == ""
    assert result["action_feedback"] == learning.action_feedback(correct, confidence)
    if not confidence:
        assert result["action_feedback"] == "" and result["confidence_status"] == "unmarked"
    assert result["score"] == int(correct)
    stat = summary(client, auth, uid)
    assert stat["accuracy"] == int(correct) * 100 and stat["effective_count"] == 1
    assert stat["unmarked_count"] == 1
    assert stat["wrong_count"] == int(not correct) and stat["consolidate_count"] == int(not correct)
    repeated = submit(client, auth, uid, quiz, correct=not correct, confidence="high" if confidence != "high" else "low")
    assert repeated["attempt_id"] == result["attempt_id"] and repeated["confidence"] == ""
    assert repeated["correct"] == correct
    loaded = data(client.get(f"/api/quizzes/{quiz['quiz_id']}", headers=auth(uid)))
    assert loaded["results"][quiz["questions"][0]["id"]]["confidence"] == ""
    assert len(library(client, auth, uid)[0]["history"]) == 1


def test_feedback_edit_dedup_withdraw_restore_and_question_isolation(client, auth):
    uid = "feedback-cycle"
    quiz = create(client, auth, uid, count=2)
    original = submit(client, auth, uid, quiz, confidence="high", correct=False)
    submit(client, auth, uid, quiz, index=1, confidence="low", correct=True)
    saved = data(report(client, auth, uid, quiz))
    assert saved["message"] == learning.REPORT_SUCCESS and saved["attempt_id"] == original["attempt_id"]
    assert saved["storage"] == "server" and saved["lecture_id"] == "lec-6"
    stat = summary(client, auth, uid)
    assert (stat["accuracy"], stat["effective_count"], stat["wrong_count"], stat["consolidate_count"], stat["reported_count"]) == (100, 1, 0, 0, 1)
    items = library(client, auth, uid)
    flagged = next(x for x in items if x["excluded"])
    assert flagged["action_feedback"] == learning.REPORT_NOTE and not flagged["review_recommended"]
    assert flagged["correct"] is False and flagged["confidence"] == ""
    assert len(data(client.get("/api/mistakes", headers=auth(uid)))["items"]) == 0
    assert client.post("/api/quizzes", headers=auth(uid), json={"mode": "review", "question_ids": [flagged["id"]]}).status_code == 404
    edited = data(report(client, auth, uid, quiz, category="source", reason="这段原文不对应"))
    repeated = data(report(client, auth, uid, quiz, category="source", reason="这段原文不对应"))
    assert edited["bad_case_id"] == repeated["bad_case_id"] == saved["bad_case_id"]
    path = f"/api/practice/reports/{flagged['id']}"
    refreshed = data(client.get(path, headers=auth(uid)))
    assert refreshed["category"] == "source" and refreshed["reason"] == "这段原文不对应"
    with service.SessionLocal() as session:
        assert len(session.scalars(select(BadCase).where(BadCase.user_id == uid)).all()) == 1
        assert len(session.scalars(select(StudyEvent).where(StudyEvent.user_id == uid, StudyEvent.name == "practice_question_feedback")).all()) == 1
    assert client.delete(path, headers=auth("outsider")).status_code == 404
    withdrawn = data(client.delete(path, headers=auth(uid)))
    assert not withdrawn["active"] and withdrawn["message"] == "已撤回反馈，本题已恢复参与学习统计。"
    stat = summary(client, auth, uid)
    assert (stat["accuracy"], stat["wrong_count"], stat["consolidate_count"], stat["reported_count"]) == (50, 1, 1, 0)
    restored = next(x for x in library(client, auth, uid) if x["id"] == flagged["id"])
    assert not restored["priority"] and restored["attempt_id"] == original["attempt_id"] and restored["history_count"] == 1


@pytest.mark.parametrize("withdraw", [False, True])
def test_transaction_failure_does_not_change_state(client, auth, monkeypatch, withdraw):
    uid = f"failed-feedback-{withdraw}"
    quiz = create(client, auth, uid, count=1)
    submit(client, auth, uid, quiz, correct=False, confidence="high")
    if withdraw:
        data(report(client, auth, uid, quiz))
    before = summary(client, auth, uid)
    def fail(_):
        raise OperationalError("injected commit failure", {}, Exception("offline"))
    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail)
        response = client.delete(f"/api/practice/reports/{quiz['questions'][0]['id']}", headers=auth(uid)) if withdraw else report(client, auth, uid, quiz)
        assert response.status_code == 503
    assert summary(client, auth, uid) == before
    loaded = data(client.get(f"/api/practice/reports/{quiz['questions'][0]['id']}", headers=auth(uid)))
    assert loaded["active"] == withdraw


def test_unanswered_feedback_all_excluded_and_empty_boundary(client, auth):
    uid = "empty-and-excluded"
    assert summary(client, auth, uid)["accuracy"] is None and library(client, auth, uid) == []
    quiz = create(client, auth, uid, count=1)
    qid = quiz["questions"][0]["id"]
    assert client.post("/api/practice/reports", headers=auth(uid), json={"question_id": qid}).status_code == 422
    saved = data(report(client, auth, uid, quiz))
    assert saved["attempt_id"] == ""
    answered = submit(client, auth, uid, quiz, correct=False)
    assert answered["excluded"] and answered["action_feedback"] == learning.REPORT_NOTE
    stat = summary(client, auth, uid)
    assert stat["accuracy"] is None and stat["effective_count"] == 0 and stat["reported_count"] == 1
    assert not library(client, auth, uid)[0]["review_recommended"]
    data(client.delete(f"/api/practice/reports/{qid}", headers=auth(uid)))
    assert summary(client, auth, uid)["accuracy"] == 0


def test_retake_history_latest_scope_confidence_and_root_feedback(client, auth):
    uid = "retake-lifecycle"
    quiz = create(client, auth, uid, count=1)
    first = submit(client, auth, uid, quiz, confidence="high", correct=False)
    root_id = quiz["questions"][0]["id"]
    for confidence in ("low", "medium", "high"):
        quiz = create(client, auth, uid, mode="review", question_ids=[root_id], count=1)
        latest = submit(client, auth, uid, quiz, correct=True, confidence=confidence)
        assert latest["review_passed"]
        assert latest["learning_state"] == "normal"
        stat = summary(client, auth, uid)
        assert stat["effective_count"] == 1 and stat["accuracy"] == 100
    item = library(client, auth, uid)[0]
    assert item["history_count"] == 4 and item["history"][0]["attempt_id"] == first["attempt_id"]
    assert len({a["attempt_id"] for a in item["history"]}) == 4
    data(report(client, auth, uid, quiz))
    assert summary(client, auth, uid)["accuracy"] is None
    assert all(h["excluded"] for h in library(client, auth, uid)[0]["history"])
    data(client.delete(f"/api/practice/reports/{quiz['questions'][0]['id']}", headers=auth(uid)))
    assert summary(client, auth, uid)["accuracy"] == 100 and library(client, auth, uid)[0]["history_count"] == 4


def test_recommended_order_and_exclusion(client, auth):
    uid = "review-ranking"
    quiz = create(client, auth, uid, count=5)
    for i, (correct, confidence) in enumerate([(True, "medium"), (False, "low"), (True, "low"), (False, "high"), (True, "high")]):
        submit(client, auth, uid, quiz, index=i, correct=correct, confidence=confidence)
    items = library(client, auth, uid)
    recommended = [x for x in items if x["review_recommended"]]
    assert [x["review_rank"] for x in recommended] == [0, 0]
    assert {x["id"] for x in recommended} == {quiz["questions"][i]["id"] for i in [1, 3]}
    assert all(not x["priority"] for x in recommended)
    data(report(client, auth, uid, quiz, index=3))
    assert [x["review_rank"] for x in library(client, auth, uid) if x["review_recommended"]] == [0]
    tomorrow = (service.today() + timedelta(days=1)).isoformat()
    due = data(client.get(f"/api/practice/review-due?on={tomorrow}", headers=auth(uid)))
    assert quiz["questions"][3]["id"] not in [x["question_id"] for x in due["mistakes"]]


def test_legacy_values_feedback_and_user_isolation(client, auth):
    uid = "legacy-learning"
    quiz = create(client, auth, uid, count=1)
    original = submit(client, auth, uid, quiz)
    qid = quiz["questions"][0]["id"]
    with service.SessionLocal() as session:
        a = session.scalar(select(Attempt).where(Attempt.user_id == uid, Attempt.id == original["attempt_id"]))
        a.confidence = "八成吧"
        session.add(BadCase(id="legacy-report-case", user_id=uid, capability="practice", source="question_feedback",
            input_json=json.dumps({"question_id": qid, "category": "old-type"}), fix_note="旧的说明"))
        session.commit()
    item = library(client, auth, uid)[0]
    assert item["confidence"] == "八成吧" and item["confidence_status"] == "legacy_unknown"
    assert item["excluded"] and item["report"]["category_raw"] == "old-type"
    data(client.delete(f"/api/practice/reports/{qid}", headers=auth(uid)))
    stat = summary(client, auth, uid)
    assert stat["accuracy"] == 100 and stat["unmarked_count"] == 0 and stat["legacy_unknown_count"] == 1
    assert library(client, auth, uid)[0]["confidence"] == "八成吧"
    assert library(client, auth, "other-user") == []
    assert client.get(f"/api/practice/reports/{qid}", headers=auth("other-user")).status_code == 404


def test_concurrent_report_only_one_active_record(client, auth):
    uid = "duplicate-feedback"
    quiz = create(client, auth, uid, count=1)
    qid = quiz["questions"][0]["id"]
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: save_report(uid, qid, "重复点击", "other"), range(3)))
    assert len({r["bad_case_id"] for r in results}) == 1
    assert summary(client, auth, uid)["reported_count"] == 1


def test_retake_keeps_original_target_and_immediate_parent(client, auth, monkeypatch):
    uid = "original-target"
    quiz = create(client, auth, uid, count=1)
    root_q = quiz["questions"][0]
    submit(client, auth, uid, quiz, correct=False)
    first = create(client, auth, uid, mode="review", count=1)
    submit(client, auth, uid, first, correct=True, confidence="low")
    original_generate = service.generate
    captured = []
    def capture(*args, **kwargs):
        captured.append(args[5] if len(args) > 5 else kwargs["original"])
        return original_generate(*args, **kwargs)
    monkeypatch.setattr(service, "generate", capture)
    second = create(client, auth, uid, mode="review", question_ids=[root_q["id"]], count=1)
    assert captured[0]["stem"] == root_q["stem"]
    assert captured[0]["question_id"] == first["questions"][0]["id"]
    with service.SessionLocal() as session:
        q = service.question(session, uid, second["questions"][0]["id"])
        meta = service.meta(q)
        assert meta["original_id"] == root_q["id"] and meta["parent_question_id"] == first["questions"][0]["id"]


def test_feedback_does_not_change_other_pdf_statistics(client, auth, monkeypatch):
    uid = "pdf-stats-isolation"
    monkeypatch.setattr(service, "fetch_lecture_pages", lambda uid, lecture: [{"page": 1, "text": f"{lecture} 的公开样例原文。"}])
    first = create(client, auth, uid, lecture_id="pdf-one", count=1)
    second = create(client, auth, uid, lecture_id="pdf-two", count=1)
    submit(client, auth, uid, first, correct=False, confidence="high")
    submit(client, auth, uid, second, correct=True, confidence="low")
    before = data(client.get("/api/practice/stats?lecture_id=pdf-two", headers=auth(uid)))
    data(report(client, auth, uid, first))
    first_stats = data(client.get("/api/practice/stats?lecture_id=pdf-one", headers=auth(uid)))
    assert first_stats["accuracy"] is None and first_stats["reported_count"] == 1
    assert data(client.get("/api/practice/stats?lecture_id=pdf-two", headers=auth(uid))) == before
    assert before["accuracy"] == 100 and before["consolidate_count"] == 0
    assert len(data(client.get("/api/practice/learning?lecture_id=pdf-two", headers=auth(uid)))["items"]) == 1


def test_manual_review_accepts_normal_answer_without_changing_recommendations(client, auth):
    uid = "manual-normal-review"
    quiz = create(client, auth, uid, count=3)
    submit(client, auth, uid, quiz, index=0, correct=True, confidence="high")
    submit(client, auth, uid, quiz, index=1, correct=False, confidence="high")
    submit(client, auth, uid, quiz, index=2, correct=True, confidence="medium")
    ids = [q["id"] for q in quiz["questions"]]
    normal = next(x for x in library(client, auth, uid) if x["question_id"] == ids[0])
    assert not normal["review_recommended"]
    # 单选一题、count更大也不自动补入其他错题或待巩固题。
    revised = create(client, auth, uid, mode="review", question_ids=[ids[0]], count=5)
    assert len(revised["questions"]) == 1
    with service.SessionLocal() as session:
        q = service.question(session, uid, revised["questions"][0]["id"])
        assert service.root(q) == ids[0]
    assert not next(x for x in library(client, auth, uid) if x["root_id"] == ids[0])["review_recommended"]
    # 只选首尾两题，不能自动加入中间那道优先错题。
    selected = create(client, auth, uid, mode="review", question_ids=[ids[0], ids[2]], count=2)
    with service.SessionLocal() as session:
        assert {service.root(service.question(session, uid, q["id"])) for q in selected["questions"]} == {ids[0], ids[2]}
    data(report(client, auth, uid, quiz, index=0))
    response = client.post("/api/quizzes", headers=auth(uid), json={"mode": "review", "question_ids": [ids[0]], "count": 1})
    assert response.status_code == 404


def test_manual_selection_is_not_silently_truncated(client, auth):
    uid = "manual-review-limit"
    quiz = create(client, auth, uid, count=2)
    for index in range(2):
        submit(client, auth, uid, quiz, index=index, correct=False)
    ids = [q["id"] for q in quiz["questions"]]
    response = client.post("/api/quizzes", headers=auth(uid), json={"mode": "review", "question_ids": ids, "count": 1})
    assert response.status_code == 422 and "超过本次题数" in response.text
    response = client.post("/api/quizzes", headers=auth(uid), json={"mode": "review", "question_ids": ids * 8, "count": 15})
    assert response.status_code == 422


@pytest.mark.parametrize("correct", [True, False])
@pytest.mark.parametrize("old_confidence", ["", "low", "medium", "high", "八成吧"])
def test_existing_confidence_is_preserved_but_never_classifies_or_prioritizes(client, auth, correct, old_confidence):
    uid = f"legacy-round3-{correct}-{old_confidence}"
    quiz = create(client, auth, uid, count=1)
    first = submit(client, auth, uid, quiz, correct=correct)
    with service.SessionLocal() as session:
        attempt = session.scalar(select(Attempt).where(Attempt.user_id == uid, Attempt.id == first["attempt_id"]))
        attempt.confidence = old_confidence
        session.commit()
    item = library(client, auth, uid)[0]
    assert item["learning_state"] == ("normal" if correct else "wrong")
    assert item["review_recommended"] == (not correct) and not item["priority"]
    assert item["action_feedback"] == ""
    stats = summary(client, auth, uid)
    assert stats["correct_count"] == int(correct)
    assert stats["wrong_count"] == stats["consolidate_count"] == int(not correct)
    assert stats["accuracy"] == 100 * int(correct)
    saved = data(report(client, auth, uid, quiz))
    assert summary(client, auth, uid)["accuracy"] is None
    data(client.delete(f"/api/practice/reports/{saved['question_id']}", headers=auth(uid)))
    assert summary(client, auth, uid)["accuracy"] == 100 * int(correct)
    with service.SessionLocal() as session:
        attempt = session.scalar(select(Attempt).where(Attempt.user_id == uid, Attempt.id == first["attempt_id"]))
        assert attempt.confidence == old_confidence and attempt.correct == int(correct)
    assert library(client, auth, uid)[0]["history_count"] == 1


def test_new_answers_and_drafts_do_not_collect_confidence(client, auth):
    from app.study.practice.schemas import AttemptBody, ProgressBody
    assert "confidence" not in AttemptBody.model_fields and "confidence" not in ProgressBody.model_fields
    uid = "no-new-confidence"
    quiz = create(client, auth, uid, count=1)
    qid = quiz["questions"][0]["id"]
    path = f"/api/quizzes/{quiz['quiz_id']}/progress"
    saved = data(client.patch(path, json={"question_id": qid, "answer": "B", "paused": True, "confidence": "high"}, headers=auth(uid)))
    assert "confidence" not in saved["progress"]
    assert "confidence" not in data(client.get(f"/api/quizzes/{quiz['quiz_id']}", headers=auth(uid)))["progress"]
    answered = submit(client, auth, uid, quiz, correct=True, confidence="high")
    with service.SessionLocal() as session:
        attempt = session.scalar(select(Attempt).where(Attempt.user_id == uid, Attempt.id == answered["attempt_id"]))
        assert attempt.confidence == ""  # 共用表非空列仅保留空占位，不存入旧客户端传来的值。
