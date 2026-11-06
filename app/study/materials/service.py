"""Stage 1: real upload, durable page extraction, and explicit failure states.

``parsed`` means the source text is available, not that AI notes are ready.
No notes or learning completion is fabricated by this module.
"""

from __future__ import annotations

import hashlib
import os
import threading
import uuid
from typing import Any

from sqlalchemy import delete, select

from app.data_access import user_scope
from app.data_access.session import SessionLocal
from app.gateway.llm_gateway import has_llm
from app.study.common.db import ensure_schema
from app.study.common.models import KbDocument, MaterialPage, StudyFile, _now
from app.study.materials import parser, storage
from app.study.materials.errors import MaterialError, MaterialNotFound

_LOCK = threading.RLock()


def _owned(session, user_id: str, file_id: str) -> StudyFile:
    row = session.scalar(select(StudyFile).where(StudyFile.id == file_id, StudyFile.user_id == user_id))
    if row is None or not row.storage_path.startswith(storage.PATH_PREFIX):
        raise MaterialNotFound()
    return row


def _pid_alive(pid: Any) -> bool:
    try:
        if not isinstance(pid, int) or pid <= 0:
            return False
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _kb_status(session, user_id: str, file_id: str, status: str) -> None:
    row = session.scalar(select(KbDocument).where(KbDocument.user_id == user_id, KbDocument.file_id == file_id))
    if row is None:
        session.add(KbDocument(id=uuid.uuid4().hex, user_id=user_id, file_id=file_id, status=status))
    else:
        row.status = status


def _status(row: StudyFile, state: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.id,
        "file_id": row.id,
        "filename": row.filename,
        "lecture_id": row.lecture_id,
        "parse_status": row.parse_status,
        "kb_status": row.parse_status,
        "page_count": state.get("page_count", 0),
        "processed_pages": state.get("processed_pages", 0),
        "error": state.get("error"),
        "can_retry": row.parse_status == "failed" and storage.raw_available(row.user_id, row.id),
        "size_bytes": state.get("size_bytes", 0),
        "reused": bool(state.get("duplicate_of")),
        "duplicate_of": state.get("duplicate_of"),
        "notes_ready": row.parse_status == "ready" and bool(state.get("note_id")),
        "note_id": state.get("note_id"),
        "summary_status": state.get("summary_status", "not_started"),
        "summary_error": state.get("summary_error"),
        "storage_provider": state.get("storage_provider", "local"),
        "mock": False,
        "created_at": row.created_at,
    }


def create_upload(user_id: str, filename: str, mime: str) -> dict[str, Any]:
    name = (filename or "").strip()
    if not name or len(name) > 200 or "\x00" in name or not name.casefold().endswith(".pdf"):
        raise MaterialError("pdf_required", "请选择文件名以 .pdf 结尾的文字版 PDF")
    if mime not in ("", "application/pdf", "application/octet-stream"):
        raise MaterialError("pdf_required", "这一版只支持文字版 PDF")
    ensure_schema()
    file_id = uuid.uuid4().hex
    with _LOCK, SessionLocal() as session:
        row = StudyFile(
            id=file_id, user_id=user_id, filename=name, mime="application/pdf",
            storage_path=storage.storage_key(user_id, file_id), parse_status="awaiting_upload", lecture_id="", created_at=_now(),
        )
        session.add(row)
        storage.write_state(user_id, file_id, {"page_count": 0, "processed_pages": 0, "error": None})
        session.commit()
    return {
        "file_id": file_id,
        "upload_url": f"/api/files/{file_id}/raw",
        "method": "PUT",
        "headers": {"Content-Type": "application/pdf"},
        "expires_in": 600,
        "max_bytes": storage.MAX_FILE_BYTES,
        "mock": False,
    }


def check_upload_owner(user_id: str, file_id: str) -> None:
    ensure_schema()
    with SessionLocal() as session:
        _owned(session, user_id, file_id)


def put_bytes(user_id: str, file_id: str, content: bytes) -> dict[str, Any]:
    # Validate the entire request before replacing a previously saved file.
    if not content:
        raise MaterialError("empty_upload", "没有收到文件内容，请重新选择 PDF")
    if len(content) > storage.MAX_FILE_BYTES:
        raise MaterialError("file_too_large", "文件不能超过 20 MB，请按讲拆分", 413)
    if b"%PDF-" not in content[:1024]:
        raise MaterialError("pdf_required", "收到的文件不是有效的 PDF，请重新选择")
    digest = hashlib.sha256(content).hexdigest()
    with _LOCK, SessionLocal() as session:
        row = _owned(session, user_id, file_id)
        previous = storage.read_state(user_id, file_id)
        if row.parse_status in ("parsed", "reading", "ready"):
            if row.sha256 == digest:
                return _status(row, previous)
            raise MaterialError("file_in_use", "这份资料已经开始处理，请重新上传为一个新文件", 409)
        row.storage_path = storage.save_bytes(user_id, file_id, content)
        row.sha256 = digest
        row.parse_status = "uploaded"
        state = {"page_count": 0, "processed_pages": 0, "error": None, "size_bytes": len(content), "storage_provider": storage.provider_name()}
        storage.write_state(user_id, file_id, state)
        session.commit()
        return _status(row, state)


def file_status(user_id: str, file_id: str) -> dict[str, Any]:
    ensure_schema()
    with _LOCK, SessionLocal() as session:
        row = _owned(session, user_id, file_id)
        state = storage.read_state(user_id, file_id)
        # A process restart must not leave a permanent "reading" spinner.
        if row.parse_status == "reading" and not _pid_alive(state.get("worker_pid")):
            row.parse_status = "failed"
            state["error"] = {"code": "processing_interrupted", "message": "读取被中断了，原文件还在，可以重试"}
            storage.write_state(user_id, file_id, state)
            _kb_status(session, user_id, file_id, "failed")
            session.commit()
        canonical = state.get("duplicate_of")
        if canonical:
            owner = _owned(session, user_id, canonical)
            if owner.lecture_id == row.lecture_id and owner.sha256 == row.sha256:
                upstream = storage.read_state(user_id, canonical)
                for key in ("summary_status", "summary_error", "note_id", "summary_worker_pid"):
                    if key in upstream:
                        state[key] = upstream[key]
                if owner.parse_status == "ready" and state.get("note_id"):
                    row.parse_status = "ready"
                    _kb_status(session, user_id, file_id, "ready")
                    session.commit()
        if state.get("summary_status") in ("pending", "generating") and not _pid_alive(state.get("summary_worker_pid")):
            state["summary_status"] = "failed"
            state["summary_error"] = {"code": "summary_interrupted", "message": "笔记整理被中断了，正文已保留，可以重试整理"}
            target = storage.read_state(user_id, canonical) if canonical else state
            target.update({"summary_status": state["summary_status"], "summary_error": state["summary_error"]})
            storage.write_state(user_id, canonical or file_id, target)
        return _status(row, state)


def list_files(user_id: str) -> list[dict[str, Any]]:
    ensure_schema()
    with SessionLocal() as session:
        ids = list(session.scalars(select(StudyFile.id).where(
            StudyFile.user_id == user_id,
            StudyFile.storage_path.startswith(storage.PATH_PREFIX),
        ).order_by(StudyFile.created_at.desc(), StudyFile.id.desc())))
    return [file_status(user_id, file_id) for file_id in ids]


def start_processing(user_id: str, file_id: str, lecture_id: str) -> tuple[dict[str, Any], str | None]:
    lecture = (lecture_id or "").strip()
    if not lecture or len(lecture) > 200:
        raise MaterialError("lecture_required", "请先选择这份课件属于哪一讲")
    # Recover a dead worker before deciding whether this is a retry.
    file_status(user_id, file_id)
    with _LOCK, SessionLocal() as session:
        row = _owned(session, user_id, file_id)
        state = storage.read_state(user_id, file_id)
        if row.parse_status in ("parsed", "reading", "ready"):
            if row.lecture_id != lecture:
                raise MaterialError("lecture_conflict", "这份资料已关联另一讲，请重新上传后选择讲次", 409)
            return _status(row, state), None
        if not row.sha256 or not storage.raw_available(user_id, file_id):
            raise MaterialError("upload_required", "文件还没有上传成功，请先上传 PDF", 409)
        row.lecture_id = lecture
        # A repeated file in this user's same lecture can reuse stored pages.
        candidates = session.scalars(select(StudyFile).where(
            StudyFile.user_id == user_id, StudyFile.id != file_id,
            StudyFile.sha256 == row.sha256, StudyFile.lecture_id == lecture,
            StudyFile.parse_status.in_(("parsed", "ready")), StudyFile.storage_path.startswith(storage.PATH_PREFIX),
        ).order_by(StudyFile.created_at.desc(), StudyFile.id.desc())).all()
        for other in candidates:
            other_state = storage.read_state(user_id, other.id)
            canonical = other_state.get("duplicate_of") or other.id
            source = session.scalar(select(StudyFile).where(
                StudyFile.id == canonical, StudyFile.user_id == user_id,
                StudyFile.lecture_id == lecture, StudyFile.sha256 == row.sha256,
                StudyFile.parse_status.in_(("parsed", "ready")),
            ))
            if source is None:
                continue
            available = session.scalar(select(MaterialPage.id).where(
                MaterialPage.user_id == user_id, MaterialPage.file_id == canonical,
            ).limit(1))
            if not available:
                continue
            row.parse_status = "parsed"
            state.update({
                "page_count": other_state.get("page_count", 0),
                "processed_pages": other_state.get("page_count", 0),
                "duplicate_of": canonical, "error": None, "finished_at": _now(),
            })
            storage.write_state(user_id, file_id, state)
            _kb_status(session, user_id, file_id, "parsed")
            session.commit()
            return _status(row, state), None
        job = uuid.uuid4().hex
        row.parse_status = "reading"
        state.update({
            "page_count": 0, "processed_pages": 0, "error": None,
            "job_id": job, "worker_pid": os.getpid(), "duplicate_of": None,
        })
        storage.write_state(user_id, file_id, state)
        _kb_status(session, user_id, file_id, "reading")
        session.commit()
        return _status(row, state), job


def process_file(user_id: str, file_id: str, job_id: str) -> None:
    """Background task. Request authentication is carried explicitly into work."""
    with user_scope(user_id):
        try:
            with SessionLocal() as session:
                row = _owned(session, user_id, file_id)
                lecture = row.lecture_id

            def progress(done: int, total: int) -> None:
                with _LOCK:
                    state = storage.read_state(user_id, file_id)
                    if state.get("job_id") != job_id:
                        raise MaterialError("processing_interrupted", "读取被中断了，可以重试")
                    state.update({"page_count": total, "processed_pages": done})
                    storage.write_state(user_id, file_id, state)

            pages = parser.extract_pages(storage.ensure_raw_file(user_id, file_id), progress)
            with _LOCK, SessionLocal() as session:
                row = _owned(session, user_id, file_id)
                state = storage.read_state(user_id, file_id)
                if state.get("job_id") != job_id or row.parse_status != "reading":
                    return
                session.execute(delete(MaterialPage).where(MaterialPage.user_id == user_id, MaterialPage.file_id == file_id))
                session.add_all([
                    MaterialPage(id=uuid.uuid4().hex, user_id=user_id, lecture_id=lecture, file_id=file_id, page_no=page["page"], text=page["text"])
                    for page in pages
                ])
                row.parse_status = "parsed"
                _kb_status(session, user_id, file_id, "parsed")
                state.update({"page_count": len(pages), "processed_pages": len(pages), "error": None, "finished_at": _now(),
                              "summary_status": "pending", "summary_worker_pid": os.getpid()})
                # Persist the pending handoff before publishing parsed source so
                # a browser poll cannot stop between extraction and AI startup.
                storage.write_state(user_id, file_id, state)
                session.commit()
        except Exception as exc:
            error = exc if isinstance(exc, MaterialError) else MaterialError("processing_failed", "读取暂时没有完成，原文件还在，可以重试")
            with _LOCK, SessionLocal() as session:
                row = _owned(session, user_id, file_id)
                state = storage.read_state(user_id, file_id)
                if state.get("job_id") != job_id:
                    return
                row.parse_status = "failed"
                state["summary_status"] = "not_started"
                _kb_status(session, user_id, file_id, "failed")
                state["error"] = {"code": error.code, "message": error.message}
                storage.write_state(user_id, file_id, state)
                session.commit()
            return
        # Source extraction and AI generation have separate failure states.
        data, summary_job = start_summarizing(user_id, file_id)
        if summary_job:
            process_summary(user_id, file_id, summary_job)


def start_summarizing(user_id: str, file_id: str) -> tuple[dict[str, Any], str | None]:
    from app.study.materials import notes

    file_status(user_id, file_id)
    with _LOCK, SessionLocal() as session:
        uploaded = _owned(session, user_id, file_id)
        if uploaded.parse_status not in ("parsed", "ready"):
            raise MaterialError("source_not_ready", "请先完成 PDF 读取，再整理笔记", 409)
        alias_state = storage.read_state(user_id, file_id)
        canonical_id = alias_state.get("duplicate_of") or file_id
        row = _owned(session, user_id, canonical_id)
        if row.lecture_id != uploaded.lecture_id or row.sha256 != uploaded.sha256:
            raise MaterialError("source_mismatch", "资料版本不一致，请重新上传", 409)
        state = storage.read_state(user_id, canonical_id)
        saved = notes.get_for_file(user_id, canonical_id)
        if saved:
            state.update({"summary_status": "ready", "summary_error": None, "note_id": saved["id"]})
            row.parse_status = uploaded.parse_status = "ready"
            _kb_status(session, user_id, canonical_id, "ready")
            _kb_status(session, user_id, file_id, "ready")
            storage.write_state(user_id, canonical_id, state)
            if canonical_id != file_id:
                alias_state.update({key: state[key] for key in ("summary_status", "summary_error", "note_id")})
                storage.write_state(user_id, file_id, alias_state)
            session.commit()
            return _status(uploaded, alias_state if canonical_id != file_id else state), None
        if state.get("summary_status") == "generating" and _pid_alive(state.get("summary_worker_pid")):
            alias_state.update({key: state.get(key) for key in ("summary_status", "summary_error", "note_id", "summary_worker_pid")})
            return _status(uploaded, alias_state), None
        if not has_llm(task="materials.summary"):
            state.update({"summary_status": "unavailable", "summary_error": {"code": "model_not_configured", "message": "正文已读取。请在后端配置模型服务，再点重试整理；不要把密钥发到聊天里。"}})
            storage.write_state(user_id, canonical_id, state)
            alias_state.update({key: state[key] for key in ("summary_status", "summary_error")})
            return _status(uploaded, alias_state), None
        job = uuid.uuid4().hex
        state.update({"summary_status": "generating", "summary_error": None, "summary_job_id": job, "summary_worker_pid": os.getpid()})
        storage.write_state(user_id, canonical_id, state)
        alias_state.update({key: state.get(key) for key in ("summary_status", "summary_error", "summary_worker_pid")})
        return _status(uploaded, alias_state), job


def process_summary(user_id: str, file_id: str, job_id: str) -> None:
    from app.study.materials import notes, summary

    with user_scope(user_id):
        with SessionLocal() as session:
            uploaded = _owned(session, user_id, file_id)
            alias = storage.read_state(user_id, file_id)
            canonical_id = alias.get("duplicate_of") or file_id
            source = _owned(session, user_id, canonical_id)
            lecture, title = source.lecture_id, source.filename.removesuffix(".pdf")
            rows = session.scalars(select(MaterialPage).where(
                MaterialPage.user_id == user_id, MaterialPage.file_id == canonical_id,
            ).order_by(MaterialPage.page_no)).all()
            pages = [{"page": item.page_no, "text": item.text} for item in rows]
        try:
            state = storage.read_state(user_id, canonical_id)
            if state.get("summary_job_id") != job_id:
                return
            generated = summary.generate_notes(user_id, pages, title=title)
            saved = notes.save_generated(user_id, canonical_id, lecture, title, generated)
            with _LOCK, SessionLocal() as session:
                row = _owned(session, user_id, canonical_id)
                state = storage.read_state(user_id, canonical_id)
                if state.get("summary_job_id") != job_id:
                    return
                row.parse_status = "ready"
                _kb_status(session, user_id, canonical_id, "ready")
                state.update({"summary_status": "ready", "summary_error": None, "note_id": saved["id"]})
                storage.write_state(user_id, canonical_id, state)
                session.commit()
        except Exception as exc:
            error = exc if isinstance(exc, MaterialError) else MaterialError("summary_failed", "笔记暂时没有整理完成，正文已保留，可以重试整理")
            with _LOCK:
                state = storage.read_state(user_id, canonical_id)
                if state.get("summary_job_id") != job_id:
                    return
                state["summary_status"] = "unavailable" if error.code == "model_not_configured" else "failed"
                state["summary_error"] = {"code": error.code, "message": error.message}
                storage.write_state(user_id, canonical_id, state)
