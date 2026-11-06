"""计划线 · 做了就自动勾上（交接文档：资料交完勾掉学新的、题做完勾任务）。"""

from __future__ import annotations

import pytest

from tests.materials_pdf_helpers import pdf_bytes


@pytest.fixture
def demo_on(monkeypatch):
    monkeypatch.setenv("XIAOMAN_DEMO_CLOCK", "1")


def _plan(client, headers):
    return client.get("/api/plan/today", headers=headers).json()["data"]


def _task(plan, kind):
    return next(t for t in plan["tasks"] if t["kind"] == kind)


def test_handing_in_the_lecture_ticks_learn_and_moves_progress(client, auth, demo_on):
    headers = auth("auto-upload")
    plan = _plan(client, headers)
    learn = _task(plan, "learn")
    assert learn["title"] == "交第 7 讲课件" and learn["status"] == "todo"
    # 先真实上传、读取；计划线只接受整个资料流程完成后的 ready 信号。
    file_id = client.post("/api/files/upload-url", json={"filename": "第7讲.pdf"}, headers=headers).json()["data"]["file_id"]
    client.put(f"/api/files/{file_id}/raw", content=pdf_bytes("Lecture seven."), headers={**headers, "Content-Type": "application/pdf"})
    client.post(f"/api/files/{file_id}/complete", json={"lecture_id": "lec-7"}, headers=headers)
    assert client.get(f"/api/files/{file_id}/status", headers=headers).json()["data"]["parse_status"] == "parsed"
    assert _task(_plan(client, headers), "learn")["status"] == "todo"
    # 隔离计划线的验收：模拟后续笔记生成完成，不把 parsed 当成 ready。
    from app.study.common import store
    store.complete_file("auto-upload", file_id, "lec-7")
    after = _plan(client, headers)
    assert after["auto_completed"] == [learn["id"]]
    assert _task(after, "learn")["status"] == "done"
    assert _plan(client, headers)["auto_completed"] == []  # 只勾一次
    client.post("/api/demo/clock", json={"days": 1}, headers=headers)
    learn2 = _task(_plan(client, headers), "learn")
    assert learn2["ref"]["lecture_no"] == 8  # 进度推进了


def test_answering_the_lectures_questions_ticks_practice_right_or_wrong(client, auth):
    headers = auth("auto-practice")
    plan = _plan(client, headers)
    practice = _task(plan, "practice")
    # 第 6 讲只有 2 道题（地基样例），题不够 5 道时以现有题数为准；一对一错也算做完
    client.post("/api/attempts", json={"question_id": "auto-practice:q1", "answer": "A"}, headers=headers)
    assert _task(_plan(client, headers), "practice")["status"] == "todo"
    client.post("/api/attempts", json={"question_id": "auto-practice:q2", "answer": "B"}, headers=headers)
    after = _plan(client, headers)
    assert practice["id"] in after["auto_completed"]
    assert _task(after, "practice")["status"] == "done"


def test_redoing_yesterdays_mistake_ticks_repair(client, auth, demo_on):
    headers = auth("auto-redo")
    _plan(client, headers)
    client.post("/api/attempts", json={"question_id": "auto-redo:q1", "answer": "A"}, headers=headers)  # 答错
    client.post("/api/demo/clock", json={"days": 1}, headers=headers)
    day2 = _plan(client, headers)
    repair = day2["tasks"][0]
    assert repair["ref"]["source"] == "mistakes" and repair["status"] == "todo"
    client.post("/api/attempts", json={"question_id": "auto-redo:q1", "answer": "A"}, headers=headers)  # 又答错也算做了
    after = _plan(client, headers)
    assert repair["id"] in after["auto_completed"]
    assert after["tasks"][0]["status"] == "done"
    assert after["first_task_id"] == after["tasks"][1]["id"]  # 接着带下一件


def test_old_attempts_do_not_tick_new_tasks(client, auth, demo_on):
    headers = auth("auto-old")
    _plan(client, headers)
    for qid in ("auto-old:q1", "auto-old:q2"):
        client.post("/api/attempts", json={"question_id": qid, "answer": "B"}, headers=headers)
    client.post("/api/demo/clock", json={"days": 1}, headers=headers)
    day2 = _plan(client, headers)
    practice = _task(day2, "practice")
    assert practice["status"] == "todo"  # 昨天的作答不算今天这件


def test_auto_ticks_finish_the_day_with_a_done_card(client, auth):
    headers = auth("auto-done")
    plan = _plan(client, headers)
    review = _task(plan, "repair")
    learn = _task(plan, "learn")
    client.patch(f"/api/tasks/{review['id']}", json={"status": "done"}, headers=headers)  # 看要点：自己勾
    client.patch(f"/api/tasks/{learn['id']}", json={"status": "done"}, headers=headers)
    for qid in ("auto-done:q1", "auto-done:q2"):
        client.post("/api/attempts", json={"question_id": qid, "answer": "B"}, headers=headers)
    after = _plan(client, headers)
    assert after["all_done"] is True and after["done_card"]["type"] == "done"
