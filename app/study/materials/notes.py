"""Persist real material notes without losing edits or learning history.

Real notes use their canonical uploaded file as provenance. They never borrow
the latest lecture version during edits, and never use the foundation mock
store's JSON slicing. Every public read/save passes the existing outbound guard.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from typing import Any

from sqlalchemy import select

from app.agent.harness.guardrails import guard_text
from app.data_access.session import SessionLocal
from app.study.common.db import ensure_schema
from app.study.common.models import Chapter, Course, KnowledgePoint, MaterialPage, Note, StudyFile, _now
from app.study.materials import storage
from app.study.materials.errors import MaterialError, MaterialNotFound
from app.study.materials.summary import source_hash, validate_note_content

LABEL = "AI 整理，可以改"
NOTE_PREFIX = "materials:"
MAX_NOTE_BYTES = 256 * 1024
_LOCK = threading.RLock()


def _note_id(file_id: str) -> str:
    return NOTE_PREFIX + file_id


def _point_id(note_id: str, index: int) -> str:
    digest = hashlib.sha256(f"{note_id}:{index}".encode()).hexdigest()[:32]
    return "materials-kp:" + digest


def _json(content: dict[str, Any]) -> str:
    try:
        rendered = json.dumps(content, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        raise MaterialError("notes_validation_failed", "笔记格式不正确，请重新检查后保存", 422) from None
    if len(rendered.encode("utf-8")) > MAX_NOTE_BYTES:
        raise MaterialError("notes_too_large", "笔记内容过长，请精简后保存", 422)
    return rendered


def _source(user_id: str, file_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    ensure_schema()
    with SessionLocal() as session:
        row = session.scalar(select(StudyFile).where(
            StudyFile.id == file_id, StudyFile.user_id == user_id,
            StudyFile.storage_path.startswith(storage.PATH_PREFIX),
        ))
        if row is None:
            raise MaterialNotFound()
        state = storage.read_state(user_id, row.id)
        canonical_id = state.get("duplicate_of") or row.id
        if canonical_id != row.id:
            canonical = session.scalar(select(StudyFile).where(
                StudyFile.id == canonical_id, StudyFile.user_id == user_id,
                StudyFile.lecture_id == row.lecture_id, StudyFile.sha256 == row.sha256,
                StudyFile.storage_path.startswith(storage.PATH_PREFIX),
            ))
            if canonical is None:
                raise MaterialNotFound()
            row = canonical
        if row.parse_status not in ("parsed", "ready"):
            raise MaterialError("notes_source_unavailable", "课件正文尚不可用，请先完成 PDF 读取", 409)
        rows = session.scalars(select(MaterialPage).where(
            MaterialPage.user_id == user_id, MaterialPage.file_id == row.id,
            MaterialPage.lecture_id == row.lecture_id,
        ).order_by(MaterialPage.page_no)).all()
        if not rows:
            raise MaterialError("notes_source_unavailable", "课件正文尚不可用，请先完成 PDF 读取", 409)
        info = {"id": row.id, "lecture_id": row.lecture_id, "filename": row.filename, "sha256": row.sha256}
        pages = [{"page": page.page_no, "text": page.text, "mock": False} for page in rows]
    return info, pages


def _guard(user_id: str, title: str, content: dict[str, Any], pages: list[dict], *, where: str) -> None:
    payload = _json({"title": title, "content": content})
    # Random server IDs/hashes may contain phone-shaped digit runs. They are
    # provenance identifiers, not model-invented contact details. Mark only
    # these trusted identifiers as known inputs while still scanning all JSON.
    identifiers = [str(content.get("file_id") or ""), str(content.get("generation", {}).get("source_hash") or "")]
    identifiers.extend(str(point.get("id") or "") for point in content.get("knowledge_points", []))
    try:
        checked = guard_text(payload, user_id=user_id, inputs=tuple(page["text"] for page in pages) + tuple(identifiers), where=where)
    except Exception:
        raise MaterialError("notes_guard_unavailable", "笔记安全检查暂时无法完成，请稍后重试", 503) from None
    if checked != payload:
        raise MaterialError("notes_guard_blocked", "笔记包含无法展示的内容，请检查后重试", 422)


def _content(file_id: str, note_id: str, checked: dict, generation: dict) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "file_id": file_id,
        "summaries": checked["summaries"],
        "knowledge_points": [
            {**point, "id": _point_id(note_id, index)}
            for index, point in enumerate(checked["knowledge_points"])
        ],
        "terms": checked["terms"],
        "generation": generation,
        "points": [item["text"] for item in checked["summaries"]],
        "label": LABEL,
    }


def _parse_content(value: str) -> dict[str, Any]:
    try:
        content = json.loads(value)
    except (TypeError, ValueError):
        raise MaterialError("notes_storage_invalid", "笔记存档暂时无法读取，请稍后重试", 500) from None
    if not isinstance(content, dict) or content.get("schema_version") != 1 or not isinstance(content.get("file_id"), str):
        raise MaterialError("notes_storage_invalid", "笔记存档暂时无法读取，请稍后重试", 500)
    return content


def _public(user_id: str, record: dict[str, Any]) -> dict[str, Any]:
    content = _parse_content(record["content_json"])
    info, pages = _source(user_id, content["file_id"])
    if record["id"] != _note_id(info["id"]) or record["lecture_id"] != info["lecture_id"]:
        raise MaterialError("notes_storage_invalid", "笔记出处信息不一致，请稍后重试", 500)
    checked = validate_note_content({**content, "title": record["title"]}, pages)
    canonical = _content(info["id"], record["id"], checked, content.get("generation", {}))
    _guard(user_id, record["title"], canonical, pages, where="materials.notes.read")
    return {
        "id": record["id"], "lecture_id": record["lecture_id"], "title": record["title"],
        "label": LABEL, "edited_by_user": bool(record["edited_by_user"]),
        "point_count": len(canonical["knowledge_points"]), "term_count": len(canonical["terms"]),
        "summary_count": len(canonical["summaries"]), "mock": False, "content": canonical,
    }


def _record(row: Note) -> dict[str, Any]:
    return {
        "id": row.id, "lecture_id": row.lecture_id, "title": row.title,
        "content_json": row.content_json, "edited_by_user": row.edited_by_user,
    }


def get_note(user_id: str, note_id: str) -> dict[str, Any] | None:
    if not note_id.startswith(NOTE_PREFIX):
        return None
    ensure_schema()
    with SessionLocal() as session:
        row = session.scalar(select(Note).where(Note.id == note_id, Note.user_id == user_id))
        record = _record(row) if row is not None else None
    return _public(user_id, record) if record is not None else None


def get_for_file(user_id: str, file_id: str) -> dict[str, Any] | None:
    # Status checks also call this for unprocessed files; no saved note is a
    # normal None result, not a source-not-ready error.
    ensure_schema()
    with SessionLocal() as session:
        row = session.scalar(select(StudyFile).where(
            StudyFile.id == file_id, StudyFile.user_id == user_id,
            StudyFile.storage_path.startswith(storage.PATH_PREFIX),
        ))
        if row is None:
            return None
        canonical_id = storage.read_state(user_id, row.id).get("duplicate_of") or row.id
        if canonical_id != row.id:
            canonical = session.scalar(select(StudyFile).where(
                StudyFile.id == canonical_id, StudyFile.user_id == user_id,
                StudyFile.lecture_id == row.lecture_id, StudyFile.sha256 == row.sha256,
                StudyFile.storage_path.startswith(storage.PATH_PREFIX),
            ))
            if canonical is None:
                return None
    return get_note(user_id, _note_id(canonical_id))


def list_real_notes(user_id: str) -> list[dict[str, Any]]:
    ensure_schema()
    with SessionLocal() as session:
        rows = session.scalars(select(Note).where(
            Note.user_id == user_id, Note.id.startswith(NOTE_PREFIX),
        ).order_by(Note.created_at.desc(), Note.id.desc())).all()
        records = [_record(row) for row in rows]
    return [_public(user_id, record) for record in records]


def _write_points(session, user_id: str, lecture_id: str, note_id: str, content: dict) -> None:
    for point in content["knowledge_points"]:
        row = session.scalar(select(KnowledgePoint).where(
            KnowledgePoint.id == point["id"], KnowledgePoint.user_id == user_id,
        ))
        if row is None:
            row = KnowledgePoint(
                id=point["id"], user_id=user_id, lecture_id=lecture_id,
                name=point["name"], explanation=point["explanation"], mastery=0, next_review_on="",
            )
            session.add(row)
        else:
            row.name = point["name"]
            row.explanation = point["explanation"]
        row.source_json = _json({"file_id": content["file_id"], "note_id": note_id, "page": point["page"], "quote": point["quote"]})
        # mastery and next_review_on belong to learning history, not note edits.
    # Removed items are left as history. No question/attempt relation is deleted.


def _ensure_chapter(session, user_id: str, lecture_id: str, title: str) -> None:
    existing = session.scalar(select(Chapter).where(
        Chapter.user_id == user_id, Chapter.lecture_id == lecture_id,
    ))
    if existing is not None:
        return
    course = session.scalar(select(Course).where(Course.user_id == user_id).order_by(Course.sort_order, Course.id))
    number = re.fullmatch(r"lec-([1-9][0-9]*)", lecture_id)
    label = f"第 {int(number[1])} 讲" if number else lecture_id
    chapter_id = "materials-chapter:" + hashlib.sha256(f"{user_id}:{lecture_id}".encode()).hexdigest()[:32]
    session.add(Chapter(
        id=chapter_id, user_id=user_id, course_id=course.id if course is not None else "",
        title=f"{label} · {title}", lecture_id=lecture_id,
        sort_order=int(number[1]) if number else 0,
    ))


def save_generated(user_id: str, file_id: str, lecture_id: str, title: str, generated: dict) -> dict[str, Any]:
    info, pages = _source(user_id, file_id)
    if lecture_id != info["lecture_id"]:
        raise MaterialError("lecture_conflict", "笔记与课件所属讲次不一致", 409)
    note_id = _note_id(info["id"])
    with _LOCK:
        existing = get_note(user_id, note_id)
        if existing is not None:
            return existing
        if not isinstance(generated, dict):
            raise MaterialError("notes_validation_failed", "笔记格式不正确，请重新整理", 422)
        checked = validate_note_content(generated, pages)
        note_title = checked.get("title") or str(title or info["filename"])[:160]
        generation = generated.get("generation")
        generation = dict(generation) if isinstance(generation, dict) else {}
        digest = source_hash(pages)
        if generation.get("source_hash") not in (None, digest):
            raise MaterialError("notes_source_mismatch", "笔记对应的课件正文不一致，请重新整理", 422)
        generation["source_hash"] = digest
        content = _content(info["id"], note_id, checked, generation)
        serialized = _json(content)
        _guard(user_id, note_title, content, pages, where="materials.notes.save")
        with SessionLocal() as session:
            session.add(Note(
                id=note_id, user_id=user_id, lecture_id=lecture_id, title=note_title,
                content_json=serialized, edited_by_user=0, created_at=_now(),
            ))
            _write_points(session, user_id, lecture_id, note_id, content)
            _ensure_chapter(session, user_id, lecture_id, note_title)
            session.commit()
    result = get_note(user_id, note_id)
    assert result is not None
    return result


def update_note(user_id: str, note_id: str, content: dict, *, title: str | None = None) -> dict[str, Any]:
    with _LOCK:
        current = get_note(user_id, note_id)
        if current is None:
            raise MaterialNotFound()
        if not isinstance(content, dict):
            raise MaterialError("notes_validation_failed", "笔记格式不正确，请检查后保存", 422)
        original = current["content"]
        if content.get("file_id", original["file_id"]) != original["file_id"]:
            raise MaterialError("notes_source_mismatch", "笔记的原课件关联不能修改", 422)
        incoming = content.get("knowledge_points")
        previous = original["knowledge_points"]
        if (not isinstance(incoming, list) or len(incoming) != len(previous)
                or any(not isinstance(item, dict) or item.get("id") != before["id"]
                       or item.get("page") != before["page"] or item.get("quote") != before["quote"]
                       for item, before in zip(incoming, previous))):
            raise MaterialError("notes_identity_conflict", "请保留知识点的顺序和出处，只修改名称与解释", 422)
        info, pages = _source(user_id, original["file_id"])
        new_title = title if title is not None else content.get("title", current["title"])
        checked = validate_note_content({**content, "title": new_title}, pages)
        canonical = _content(info["id"], note_id, checked, original["generation"])
        serialized = _json(canonical)
        _guard(user_id, checked["title"], canonical, pages, where="materials.notes.edit")
        with SessionLocal() as session:
            row = session.scalar(select(Note).where(Note.id == note_id, Note.user_id == user_id))
            if row is None:
                raise MaterialNotFound()
            row.title = checked["title"]
            row.content_json = serialized
            row.edited_by_user = 1
            _write_points(session, user_id, info["lecture_id"], note_id, canonical)
            session.commit()
    result = get_note(user_id, note_id)
    assert result is not None
    return result
