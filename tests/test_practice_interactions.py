from datetime import date

import pytest

from app.study.practice import capabilities, service
from app.study.practice.schemas import CheckedQuiz, GeneratedQuiz


def create(client, auth, uid, **body):
    r = client.post("/api/quizzes", json={"lecture_id": "lec-6", **body}, headers=auth(uid))
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_fifteen_questions_and_bounds(client, auth):
    assert len(create(client, auth, "fifteen", count=15)["questions"]) == 15
    for count in (0, 16, 1.5):
        assert client.post("/api/quizzes", json={"count": count}, headers=auth("bad-count")).status_code == 422


def test_live_fifteen_is_three_batches_with_exclusions(uid, monkeypatch):
    from app.study.practice.schemas import GeneratedQuestion
    monkeypatch.setattr(capabilities, "has_llm", lambda *a, **k: True)
    seen = []
    def fake_call(user_id, name, payload, output_type, **kwargs):
        if name == "practice.check":
            return CheckedQuiz(answers=[{"index": q["index"], "answer": "A"} for q in payload["questions"]])
        offset = len(payload["exclude_stems"])
        seen.append((payload["count"], offset))
        return GeneratedQuiz(questions=[GeneratedQuestion(
            stem=f"原文依据题 {offset+i+1}", options=[{"id": "A", "text": "三件"}, {"id": "B", "text": "五件"}],
            answer="A", analysis="依据原文", source={"page": 1, "quote": "每天最多三件"}, difficulty="easy", knowledge_point="三件事")
            for i in range(payload["count"])])
    monkeypatch.setattr(capabilities, "_call", fake_call)
    qs, mock = capabilities.generate(uid, "lecture", [{"page": 1, "text": "每天最多三件"}], 15, "easy")
    assert not mock and len(qs) == 15 and seen == [(5, 0), (5, 5), (5, 10)]


def test_pause_resume_preserves_draft_and_ownership(client, auth):
    uid = "pause-owner"
    q = create(client, auth, uid, count=2)
    path = f"/api/quizzes/{q['quiz_id']}/progress"
    progress = {"question_id": q["questions"][1]["id"], "answer": "B", "paused": True, "seconds": 12}
    assert client.patch(path, json=progress, headers=auth(uid)).status_code == 200
    loaded = client.get(f"/api/quizzes/{q['quiz_id']}", headers=auth(uid)).json()["data"]
    assert loaded["progress"] == progress and loaded["results"] == {} and not loaded["completed"]
    assert client.patch(path, json=progress, headers=auth("stranger")).status_code == 404
    assert client.patch(path, json={**progress, "question_id": "foreign"}, headers=auth(uid)).status_code == 404
    assert client.patch(path, json={**progress, "paused": False}, headers=auth(uid)).json()["data"]["progress"]["paused"] is False


@pytest.mark.parametrize("category", ["answer", "ambiguous", "source", "other"])
def test_report_category_confirmation_persists_and_deduplicates(client, auth, category):
    uid = f"report-{category}"
    q = create(client, auth, uid, count=1)
    body = {"question_id": q["questions"][0]["id"], "category": category}
    response = client.post("/api/practice/reports", json=body, headers=auth(uid)).json()["data"]
    assert response["category"] == category and "暂不计入学习统计" in response["message"]
    repeated = client.post("/api/practice/reports", json=body, headers=auth(uid)).json()["data"]
    assert response["bad_case_id"] == repeated["bad_case_id"]
    loaded = client.get(f"/api/quizzes/{q['quiz_id']}", headers=auth(uid)).json()["data"]
    assert loaded["reports"][body["question_id"]]["category"] == category


def test_removed_confidence_does_not_change_classification_or_schedule(client, auth):
    outputs = []
    for confidence in ("low", "medium", "high"):
        uid = f"confidence-{confidence}"
        q = create(client, auth, uid, count=1)
        data = client.post("/api/attempts", json={"question_id": q["questions"][0]["id"], "quiz_id": q["quiz_id"],
                          "answer": "B", "confidence": confidence}, headers=auth(uid)).json()["data"]
        outputs.append(data)
    assert {d["action_feedback"] for d in outputs} == {""}
    assert all(not d["priority"] and d["learning_state"] == "normal" and d["confidence"] == "" for d in outputs)
    assert [d["mastery"] for d in outputs] == [100, 100, 100]
    day = date(2026, 11, 5)
    assert service.mastery_schedule([(True, "low")] * 2, {"repetitions": 1}, True, day, "low")["interval"] == 6
    assert service.mastery_schedule([(True, "high")] * 2, {"repetitions": 1}, True, day, "high")["interval"] == 6


def test_batch_review_can_span_lectures_without_mixing_sources(client, auth, monkeypatch):
    monkeypatch.setattr(service, "fetch_lecture_pages", lambda uid, lecture: [{"page": 1, "text": f"{lecture} 的原文内容。"}])
    uid = "mixed-review"
    ids = []
    for lecture in ("lecture-one", "lecture-two"):
        q = create(client, auth, uid, lecture_id=lecture, count=1)
        ids.append(q["questions"][0]["id"])
        client.post("/api/attempts", json={"question_id": ids[-1], "answer": "A", "quiz_id": q["quiz_id"]}, headers=auth(uid))
    reviewed = create(client, auth, uid, mode="review", question_ids=ids, count=2)
    assert len(reviewed["questions"]) == 2 and reviewed["lecture_id"] == "mixed"
    assert set(reviewed["lecture_ids"]) == {"lecture-one", "lecture-two"}
    assert "lecture-one" in str(reviewed["questions"][0]["options"])
    assert "lecture-two" in str(reviewed["questions"][1]["options"])
