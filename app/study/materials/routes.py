"""资料线：上传、学习文档、按讲取原文。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import require_user
from app.study.common import store
from app.study.common.http import missing, pack
from app.study.materials.content import fetch_lecture_pages
from app.study.materials import service, storage, notes as note_store
from app.study.materials.errors import MaterialError

router = APIRouter(tags=["资料"])


class UploadBody(BaseModel):
    filename: str = "样例.pdf"
    mime: str = "application/pdf"


class CompleteBody(BaseModel):
    lecture_id: str = ""


class NotePatch(BaseModel):
    content: dict[str, Any] = Field(default_factory=dict)
    title: str | None = Field(default=None, min_length=1, max_length=160)


def fail(error: MaterialError) -> None:
    raise HTTPException(status_code=error.http_status, detail={"code": error.code, "message": error.message})


@router.post("/api/files/upload-url")
def upload_url(body: UploadBody, user_id: str = Depends(require_user)):
    try:
        return pack(service.create_upload(user_id, body.filename, body.mime), mock=False)
    except MaterialError as error:
        fail(error)


@router.get("/api/files")
def files(user_id: str = Depends(require_user)):
    return pack({"items": service.list_files(user_id)}, mock=False)


@router.put("/api/files/{file_id}/raw")
async def upload_raw(file_id: str, request: Request, user_id: str = Depends(require_user)):
    try:
        service.check_upload_owner(user_id, file_id)
        mime = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if mime not in ("", "application/pdf", "application/octet-stream"):
            raise MaterialError("pdf_required", "请直接上传 PDF 文件内容")
        content = bytearray()
        async for chunk in request.stream():
            if len(content) + len(chunk) > storage.MAX_FILE_BYTES:
                raise MaterialError("file_too_large", "文件不能超过 20 MB，请按讲拆分", 413)
            content.extend(chunk)
        return pack(service.put_bytes(user_id, file_id, bytes(content)), mock=False)
    except MaterialError as error:
        fail(error)


@router.post("/api/files/{file_id}/complete")
def complete(file_id: str, body: CompleteBody, background_tasks: BackgroundTasks, user_id: str = Depends(require_user)):
    try:
        data, job = service.start_processing(user_id, file_id, body.lecture_id)
        if job:
            background_tasks.add_task(service.process_file, user_id, file_id, job)
        elif data["parse_status"] in ("parsed", "ready"):
            data, summary_job = service.start_summarizing(user_id, file_id)
            if summary_job:
                background_tasks.add_task(service.process_summary, user_id, file_id, summary_job)
        return pack(data, mock=False)
    except MaterialError as error:
        fail(error)


@router.get("/api/files/{file_id}/status")
def status(file_id: str, user_id: str = Depends(require_user)):
    try:
        return pack(service.file_status(user_id, file_id), mock=False)
    except MaterialError as error:
        fail(error)


@router.post("/api/files/{file_id}/summarize")
def summarize(file_id: str, background_tasks: BackgroundTasks, user_id: str = Depends(require_user)):
    try:
        data, job = service.start_summarizing(user_id, file_id)
        if job:
            background_tasks.add_task(service.process_summary, user_id, file_id, job)
        return pack(data, mock=False)
    except MaterialError as error:
        fail(error)


@router.get("/api/notes")
def notes(user_id: str = Depends(require_user)):
    try:
        real = note_store.list_real_notes(user_id)
        # Real notes must not carry the foundation sample as an unmarked result.
        return pack({"items": real if real else store.list_notes(user_id)}, mock=not bool(real))
    except MaterialError as error:
        fail(error)


@router.get("/api/notes/{note_id}")
def note_detail(note_id: str, user_id: str = Depends(require_user)):
    try:
        real = note_store.get_note(user_id, note_id)
        if real is not None:
            return pack(real, mock=False)
    except MaterialError as error:
        fail(error)
    data = store.get_note(user_id, note_id)
    if data is None:
        missing()
    return pack(data)


@router.patch("/api/notes/{note_id}")
def note_patch(note_id: str, body: NotePatch, user_id: str = Depends(require_user)):
    try:
        real = note_store.get_note(user_id, note_id)
        if real is not None:
            return pack(note_store.update_note(user_id, note_id, body.content, title=body.title), mock=False)
    except MaterialError as error:
        fail(error)
    data = store.patch_note(user_id, note_id, body.content)
    if data is None:
        missing()
    return pack(data)


@router.get("/api/lectures/{lecture_id}/pages")
def lecture_pages(lecture_id: str, file_id: str | None = None, user_id: str = Depends(require_user)):
    try:
        pages = fetch_lecture_pages(user_id, lecture_id, file_id=file_id)
        mocked = any(page.get("mock") for page in pages)
        return pack({"lecture_id": lecture_id, "pages": pages, "label": "模拟" if mocked else "正文"}, mock=mocked)
    except MaterialError as error:
        fail(error)
