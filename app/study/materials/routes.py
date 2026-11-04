"""资料线：上传、学习文档、按讲取原文。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth import require_user
from app.study.common import store
from app.study.common.http import missing, pack
from app.study.materials.content import fetch_lecture_pages

router = APIRouter(tags=["资料"])


class UploadBody(BaseModel):
    filename: str = "样例.pdf"
    mime: str = "application/pdf"


class CompleteBody(BaseModel):
    lecture_id: str = ""


class NotePatch(BaseModel):
    content: dict[str, Any] = Field(default_factory=dict)


@router.post("/api/files/upload-url")
def upload_url(body: UploadBody, user_id: str = Depends(require_user)):
    return pack(store.create_upload(user_id, body.filename, body.mime))


@router.put("/api/files/{file_id}/raw")
def upload_raw(file_id: str, user_id: str = Depends(require_user)):
    if not store.mark_uploaded(user_id, file_id):
        missing()
    return pack({"id": file_id, "parse_status": "uploaded"})


@router.post("/api/files/{file_id}/complete")
def complete(file_id: str, body: CompleteBody, user_id: str = Depends(require_user)):
    data = store.complete_file(user_id, file_id, body.lecture_id)
    if data is None:
        missing()
    return pack(data)


@router.get("/api/files/{file_id}/status")
def status(file_id: str, user_id: str = Depends(require_user)):
    data = store.file_status(user_id, file_id)
    if data is None:
        missing()
    return pack(data)


@router.get("/api/notes")
def notes(user_id: str = Depends(require_user)):
    return pack({"items": store.list_notes(user_id)})


@router.get("/api/notes/{note_id}")
def note_detail(note_id: str, user_id: str = Depends(require_user)):
    data = store.get_note(user_id, note_id)
    if data is None:
        missing()
    return pack(data)


@router.patch("/api/notes/{note_id}")
def note_patch(note_id: str, body: NotePatch, user_id: str = Depends(require_user)):
    data = store.patch_note(user_id, note_id, body.content)
    if data is None:
        missing()
    return pack(data)


@router.get("/api/lectures/{lecture_id}/pages")
def lecture_pages(lecture_id: str, user_id: str = Depends(require_user)):
    pages = fetch_lecture_pages(user_id, lecture_id)
    mocked = any(page.get("mock") for page in pages)
    return pack({"lecture_id": lecture_id, "pages": pages, "label": "模拟" if mocked else ""})
