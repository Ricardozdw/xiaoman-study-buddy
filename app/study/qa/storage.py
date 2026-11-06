"""QA persistence using the existing shared schema; no migration required."""
from __future__ import annotations

import hashlib
import json
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.data_access.session import SessionLocal
from app.study.common.db import ensure_schema
from app.study.common.models import BadCase, MaterialPage, StudyEvent, StudyFile, StudyMessage
from app.study.materials.content import SAMPLE_LECTURE_ID, SAMPLE_PAGES, fetch_lecture_pages
from .safety import clean_text, clean_payload


def _json(value):
    return json.dumps(value, ensure_ascii=False)


def _is_sample(pages):
    return any(p.get("mock") for p in pages) or [(p["page"], p["text"]) for p in pages] == [(p["page"], p["text"]) for p in SAMPLE_PAGES]


def lectures(user_id: str) -> dict:
    ensure_schema()
    with SessionLocal() as session:
        rows = session.scalars(select(MaterialPage).where(MaterialPage.user_id == user_id).order_by(MaterialPage.lecture_id, MaterialPage.page_no)).all()
        files = session.scalars(select(StudyFile).where(StudyFile.user_id == user_id).order_by(StudyFile.created_at.desc())).all()
        events = session.scalars(select(StudyEvent).where(StudyEvent.user_id == user_id, StudyEvent.name == "qa.message").order_by(StudyEvent.at.desc()).limit(100)).all()
        groups: dict[str, list] = {}
        for row in rows:
            groups.setdefault(row.lecture_id, []).append({"page": row.page_no, "text": row.text})
        titles = {row.lecture_id: row.filename for row in reversed(files) if row.lecture_id}
        items = [{"id": key, "title": titles.get(key) or key, "mock": _is_sample(pages)} for key, pages in groups.items()]
        if not items:
            items = [{"id": SAMPLE_LECTURE_ID, "title": "内置示例讲义", "mock": True}]
        ids = {item["id"] for item in items}
        recent = [json.loads(event.props_json).get("lecture_id") for event in events]
        recent.extend(row.lecture_id for row in files)
        current = next((item for item in recent if item in ids), items[0]["id"])
        return {"items": items, "current_lecture_id": current}


def lecture_content(user_id: str, lecture_id: str) -> tuple[str, list, bool]:
    available = lectures(user_id)
    chosen = lecture_id or available["current_lecture_id"]
    if chosen not in {item["id"] for item in available["items"]}:
        raise HTTPException(404, detail={"code": "lecture_not_found", "message": "没有找到这讲资料，请用 @ 选择已有资料。"})
    pages = fetch_lecture_pages(user_id, chosen)
    if not pages or not any(p.get("text", "").strip() for p in pages):
        raise HTTPException(422, detail={"code": "empty_material", "message": "这讲资料没有可用文字，请先完成资料解析。"})
    return chosen, pages, _is_sample(pages)


def claim_thread(user_id: str, thread_id: str) -> str:
    from app.main import _require_thread_owner
    from app.graph import get_thread_snapshot, update_thread_state
    ensure_schema()
    tid = thread_id or "qa-" + uuid.uuid4().hex
    _require_thread_owner(tid, user_id)
    key = "qa-thread-" + hashlib.sha256(tid.encode()).hexdigest()
    with SessionLocal() as session:
        row = session.get(StudyEvent, key)
        if row is None:
            session.add(StudyEvent(id=key, user_id=user_id, name="qa.thread", props_json="{}"))
            try:
                session.commit()
                row = session.get(StudyEvent, key)
            except IntegrityError:
                session.rollback()
                row = session.get(StudyEvent, key)
        if row is None or row.user_id != user_id:
            raise HTTPException(403, detail={"code": "thread_forbidden", "message": "会话不属于当前用户。"})
    # The unchanged global identity middleware only accepts graph-owned threads.
    # Register ownership without running a model, so later QA turns pass that gate.
    if not get_thread_snapshot(tid).get("exists"):
        update_thread_state(tid, {"user_id": user_id, "messages": []})
        if get_thread_snapshot(tid).get("user_id") != user_id:
            raise HTTPException(503, detail={"code": "thread_unavailable", "message": "会话暂时无法保存，请重试。"})
    return tid


def save_answer(user_id: str, message_id: str, text: str, refs: list, context: dict) -> None:
    ensure_schema()
    try:
        text, refs, context = clean_text(user_id, text, 30000), clean_payload(user_id, refs), clean_payload(user_id, context)
    except HTTPException:
        text, refs, context = "", [], {"ok": False, "error": "privacy_unavailable"}
    with SessionLocal() as session:
        session.add(StudyMessage(id=message_id, user_id=user_id, role="assistant", content=text, refs_json=_json(refs)))
        session.add(StudyEvent(id="qa-msg-" + message_id, user_id=user_id, name="qa.message", props_json=_json(context)))
        session.commit()


def feedback(user_id: str, message_id: str, rating: str, reason: str) -> dict:
    reason = clean_text(user_id, reason, 1000)
    ensure_schema()
    bad_id = "qa-feedback-" + message_id
    with SessionLocal() as session:
        message = session.get(StudyMessage, message_id)
        if message is None or message.user_id != user_id:
            raise HTTPException(404, detail={"code": "message_not_found", "message": "没有找到这条回答。"})
        event = session.get(StudyEvent, "qa-msg-" + message_id)
        context = json.loads(event.props_json) if event else {}
        context["reason"] = reason
        message.feedback = rating
        if rating == "down":
            existing = session.get(BadCase, bad_id)
            if existing is None:
                session.add(BadCase(id=bad_id, user_id=user_id, capability="问答", input_json=_json(context), actual_output=message.content,
                                    model=context.get("model", ""), prompt_version="qa.answer@v1", problem_type="用户反馈", severity="中", source="user_feedback"))
            elif reason:
                existing.input_json = _json(context)
        try:
            session.commit()
        except IntegrityError:
            # Concurrent duplicate feedback: the deterministic bad-case id wins once.
            session.rollback()
            message = session.get(StudyMessage, message_id)
            message.feedback = rating
            session.commit()
    return {"message_id": message_id, "feedback": rating, "bad_case_id": bad_id if rating == "down" else None}
