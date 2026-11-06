"""地基接口：形状、样例数据、AI 范例、MVP 开关。"""

from __future__ import annotations

import json

import pytest

from tests.materials_pdf_helpers import pdf_bytes

REQUIRED_PATHS = [
    "/api/files/upload-url",
    "/api/files/{file_id}/complete",
    "/api/files/{file_id}/status",
    "/api/notes",
    "/api/notes/{note_id}",
    "/api/lectures/{lecture_id}/pages",
    "/api/chat/stream",
    "/api/quizzes",
    "/api/attempts",
    "/api/mistakes",
    "/api/goals",
    "/api/goals/current",
    "/api/plan/today",
    "/api/tasks/{task_id}",
    "/api/suggestions",
    "/api/suggestions/{action_id}/accept",
    "/api/actions/{action_id}/undo",
    "/api/me/permissions",
    "/api/dashboard",
    "/api/study/example",
]


def test_study_routes_are_in_openapi(client):
    paths = client.get("/openapi.json").json()["paths"]
    missing = [path for path in REQUIRED_PATHS if path not in paths]
    assert missing == []
    assert "/api/chat" in paths


def test_plan_today_has_three_kinds(client, auth):
    response = client.get("/api/plan/today", headers=auth("study-plan"))
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and body["mock"] is True
    kinds = [task["kind"] for task in body["data"]["tasks"]]
    assert kinds == ["learn", "practice", "repair"]
    task_id = body["data"]["tasks"][0]["id"]
    done = client.patch(f"/api/tasks/{task_id}", json={"status": "done"}, headers=auth("study-plan"))
    assert done.json()["data"]["status"] == "done"
    light = client.patch("/api/plan/today", json={"intensity": "light"}, headers=auth("study-plan"))
    assert light.json()["data"]["intensity"] == "light"
    assert light.json()["data"]["minutes"] == 15
    assert sum(task["minutes"] for task in light.json()["data"]["tasks"]) == 15
    assert light.json()["data"]["tasks"][0]["status"] == "done"
    assert len(light.json()["data"]["tasks"]) == 3


def test_notes_pages_and_files(client, auth):
    headers = auth("study-files")
    notes = client.get("/api/notes", headers=headers).json()["data"]["items"]
    assert notes and notes[0]["label"] == "AI 整理，可以改"
    detail = client.get(f"/api/notes/{notes[0]['id']}", headers=headers)
    assert detail.status_code == 200
    patched = client.patch(
        f"/api/notes/{notes[0]['id']}",
        json={"content": {"points": ["用户改过的一句"], "label": "AI 整理，可以改"}},
        headers=headers,
    )
    assert patched.json()["data"]["edited_by_user"] is True
    pages = client.get("/api/lectures/lec-6/pages", headers=headers).json()["data"]["pages"]
    assert [page["page"] for page in pages] == [1, 2]
    assert "每天最多三件事" in pages[0]["text"]
    created = client.post("/api/files/upload-url", json={"filename": "a.pdf"}, headers=headers).json()["data"]
    file_id = created["file_id"]
    assert created["upload_url"].endswith("/raw")
    assert client.put(
        f"/api/files/{file_id}/raw",
        content=pdf_bytes("Actual uploaded lecture."),
        headers={**headers, "Content-Type": "application/pdf"},
    ).status_code == 200
    done = client.post(f"/api/files/{file_id}/complete", json={"lecture_id": "lec-6"}, headers=headers)
    assert done.json()["mock"] is False
    status = client.get(f"/api/files/{file_id}/status", headers=headers).json()["data"]
    assert status["parse_status"] == status["kb_status"] == "parsed"
    assert status["page_count"] == 1 and status["notes_ready"] is False
    real_pages = client.get("/api/lectures/lec-6/pages", headers=headers).json()["data"]["pages"]
    assert len(real_pages) == 1 and "Actual uploaded lecture" in real_pages[0]["text"]


def test_quiz_attempt_and_mistakes(client, auth):
    headers = auth("study-quiz")
    quiz = client.post("/api/quizzes", json={"lecture_id": "lec-6", "count": 2}, headers=headers).json()["data"]
    assert quiz["label"] == "模拟"
    assert len(quiz["questions"]) == 2
    wrong = client.post(
        "/api/attempts",
        json={"question_id": quiz["questions"][0]["id"], "answer": "A", "seconds": 3},
        headers=headers,
    ).json()["data"]
    assert wrong["correct"] is False
    mistakes = client.get("/api/mistakes", headers=headers).json()["data"]["items"]
    assert mistakes and mistakes[0]["question_id"] == quiz["questions"][0]["id"]


def test_suggestion_accept_and_undo(client, auth):
    headers = auth("study-suggest")
    items = client.get("/api/suggestions", headers=headers).json()["data"]["items"]
    action_id = items[0]["id"]
    accepted = client.post(f"/api/suggestions/{action_id}/accept", headers=headers).json()["data"]
    assert accepted["status"] == "executed"
    assert accepted["plan"]["intensity"] == "light"
    undone = client.post(f"/api/actions/{action_id}/undo", headers=headers).json()["data"]
    assert undone["status"] == "undone"
    assert undone["plan"]["intensity"] == "normal"


def test_goal_dashboard_and_permissions(client, auth):
    headers = auth("study-goal")
    goal = client.post(
        "/api/goals",
        json={"title": "样例目标", "exam_date": "2026-12-01", "lecture_count": 6, "daily_minutes": 30},
        headers=headers,
    ).json()["data"]
    assert goal["card_type"] == "goal"
    assert goal["label"] == "模拟"
    assert client.get("/api/goals/current", headers=headers).json()["data"]["title"] == "样例目标"
    board = client.get("/api/dashboard", params={"range": "week"}, headers=headers).json()["data"]
    assert board["range"] == "week"
    assert "连续" not in board["note"]
    assert board["lectures"]
    perms = client.get("/api/me/permissions", headers=headers).json()["data"]
    assert perms["chosen"] is False
    assert [item["key"] for item in perms["switches"]] == ["auto_adjust_today", "use_study_history", "more_later"]
    assert all(item["value"] is None for item in perms["switches"])
    chosen = client.patch("/api/me/permissions", json={"permissions": {"auto_adjust_today": True}}, headers=headers)
    assert chosen.json()["data"]["chosen"] is True
    assert chosen.json()["data"]["permissions"]["auto_adjust_today"] is True


def test_chat_stream_is_sse_and_base_chat_remains(client, auth):
    headers = auth("study-chat")
    with client.stream("POST", "/api/chat/stream", json={"message": "这一讲在说什么", "lecture_id": "lec-6"}, headers=headers) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
    assert body.count("data:") >= 3 and "[DONE]" in body
    pieces = []
    for line in body.splitlines():
        if line.startswith("data:") and "[DONE]" not in line:
            pieces.append(json.loads(line[5:].strip()).get("delta") or "")
    assert "模拟" in "".join(pieces)


def test_example_capability_records_usage_and_bad_case(client, auth, monkeypatch):
    headers = auth("study-ai")
    calls = {"n": 0}

    def fake_chat(system, user, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"summary": "", "page": "nope"}
        return {"summary": "每天最多三件事。", "page": 1, "label": "AI 整理，可以改", "_mode": "mock", "_model": "mock"}

    monkeypatch.setattr("app.study.common.capability.chat_json", fake_chat)
    monkeypatch.setattr("app.study.common.capability.has_llm", lambda **kwargs: False)
    ok = client.post("/api/study/example", json={"text": "每天最多三件事。", "page": 1}, headers=headers)
    assert ok.status_code == 200
    assert ok.json()["data"]["attempts"] == 2
    assert ok.json()["data"]["label"] == "AI 整理，可以改"
    assert calls["n"] == 2
    usage = client.get("/api/study/usage", headers=headers).json()["data"]
    assert usage["by_capability"]["示范"]["prompt_tokens"] > 0
    assert usage["by_capability"]["示范"]["completion_tokens"] > 0
    failed = client.post("/api/study/example", json={"text": "样例", "demo_failure": True}, headers=headers)
    assert failed.json()["ok"] is False
    assert failed.json()["data"]["bad_case_id"]
    cases = client.get("/api/study/bad-cases", headers=headers).json()["data"]["items"]
    assert cases[-1]["source"] == "foundation_demo"
    assert cases[-1]["problem_type"] == "格式错"


def test_mvp_flag_hides_unused_base_surfaces(client, auth, monkeypatch):
    headers = auth("study-mvp")
    monkeypatch.setenv("XIAOMAN_MVP", "1")
    hidden = client.post("/api/secrets", json={"kind": "note", "value": "x"}, headers=headers)
    assert hidden.status_code == 404
    assert hidden.json()["detail"]["code"] == "mvp_disabled"
    assert client.get("/api/plan/today", headers=headers).status_code == 200
    monkeypatch.setenv("XIAOMAN_MVP", "0")
    # 关掉开关后，密钥接口回到底座自己的行为（测试环境有保险库钥匙，不应再是 mvp_disabled）。
    restored = client.get("/api/secrets", headers=headers)
    assert restored.status_code != 404 or restored.json().get("detail", {}).get("code") != "mvp_disabled"


def test_mvp_disables_fetch_and_draft(monkeypatch):
    monkeypatch.setenv("XIAOMAN_MVP", "1")
    from app.agent import tool_registry
    from app.agent.tool_registry import ToolError
    from app.tools.crawl import web_fetch
    from app.tools.writing import draft_text

    with pytest.raises(ToolError) as fetched:
        web_fetch("https://example.com")
    assert fetched.value.code == "mvp_disabled"
    with pytest.raises(ToolError) as drafted:
        draft_text("写一封信", {})
    assert drafted.value.code == "mvp_disabled"
    refused = tool_registry.invoke_tool("web_search", {"query": "样例"})
    assert refused["ok"] is False
    assert refused["error"]["code"] == "mvp_disabled"


def test_study_tables_exist_after_request(client, auth):
    from sqlalchemy import inspect

    from app import db

    client.get("/api/plan/today", headers=auth("study-tables"))
    names = set(inspect(db.ENGINE).get_table_names())
    for table in (
        "goals",
        "courses",
        "chapters",
        "files",
        "kb_documents",
        "material_pages",
        "notes",
        "knowledge_points",
        "questions",
        "attempts",
        "plan_days",
        "plan_tasks",
        "agent_actions",
        "messages",
        "events",
        "llm_calls",
        "bad_cases",
        "user_settings",
    ):
        assert table in names
