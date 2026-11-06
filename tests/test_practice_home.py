from app.study.practice.feedback import CORRECT_OPENINGS, INCORRECT_OPENINGS, answer_feedback


def make(client, auth, uid, count=2):
    return client.post("/api/quizzes", json={"lecture_id": "lec-6", "count": count}, headers=auth(uid)).json()["data"]


def test_reply_pools_have_ten_unique_natural_openings_and_stable_random_choice():
    assert len(CORRECT_OPENINGS) == len(set(CORRECT_OPENINGS)) == 10
    assert len(INCORRECT_OPENINGS) == len(set(INCORRECT_OPENINGS)) == 10
    for correct, pool in [(True, CORRECT_OPENINGS), (False, INCORRECT_OPENINGS)]:
        draws = [answer_feedback(correct, "", f"attempt-{i}") for i in range(300)]
        assert set(draws) == set(pool)
        assert all("常错" not in text for text in draws)
        assert answer_feedback(correct, "high", "same-attempt") == answer_feedback(correct, "high", "same-attempt")


def test_multiple_paused_groups_survive_starting_new_practice_and_are_private(client, auth):
    uid = "home-pause-owner"
    first = make(client, auth, uid)
    progress = {"question_id": first["questions"][1]["id"], "answer": "B", "paused": True, "seconds": 9}
    assert client.patch(f"/api/quizzes/{first['quiz_id']}/progress", json=progress, headers=auth(uid)).status_code == 200
    second = make(client, auth, uid, 3)
    second_progress = {**progress, "question_id": second["questions"][0]["id"]}
    client.patch(f"/api/quizzes/{second['quiz_id']}/progress", json=second_progress, headers=auth(uid))
    paused = client.get("/api/practice/paused", headers=auth(uid)).json()["data"]["items"]
    assert {q["quiz_id"] for q in paused} == {first["quiz_id"], second["quiz_id"]}
    assert next(q for q in paused if q["quiz_id"] == first["quiz_id"])["progress"] == progress
    assert client.get("/api/practice/paused", headers=auth("other-owner")).json()["data"]["items"] == []
    client.patch(f"/api/quizzes/{first['quiz_id']}/progress", json={**progress, "paused": False}, headers=auth(uid))
    remaining = client.get("/api/practice/paused", headers=auth(uid)).json()["data"]["items"]
    assert [q["quiz_id"] for q in remaining] == [second["quiz_id"]]


def test_last_answered_group_is_not_shown_as_paused_and_feedback_survives_reload(client, auth):
    uid = "home-completed"
    q = make(client, auth, uid, 1)
    qid = q["questions"][0]["id"]
    client.patch(f"/api/quizzes/{q['quiz_id']}/progress", json={"question_id": qid, "paused": True}, headers=auth(uid))
    response = client.post("/api/attempts", json={"quiz_id": q["quiz_id"], "question_id": qid, "answer": "A"}, headers=auth(uid)).json()["data"]
    loaded = client.get(f"/api/quizzes/{q['quiz_id']}", headers=auth(uid)).json()["data"]
    assert response["feedback"] == loaded["results"][qid]["feedback"]
    assert response["feedback"] in INCORRECT_OPENINGS
    assert client.get("/api/practice/paused", headers=auth(uid)).json()["data"]["items"] == []
