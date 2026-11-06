"""Additive QA HTTP contract; existing POST /api/chat is unchanged."""
from __future__ import annotations

import json
from typing import Literal
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from app.auth import require_user
from app.study.common.http import pack
from . import storage
from .service import conversation_events

router = APIRouter(tags=["问答"])

class StreamBody(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    lecture_id: str = Field(default="", max_length=200)
    thread_id: str = Field(default="", max_length=200)

    @field_validator("message", "lecture_id", "thread_id")
    @classmethod
    def trim(cls, value, info):
        value = value.strip()
        if info.field_name == "message" and not value:
            raise ValueError("message must not be blank")
        return value

class FeedbackBody(BaseModel):
    rating: Literal["up", "down"]
    reason: str = Field(default="", max_length=1000)


def _sse(events):
    try:
        for event in events:
            yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
        yield "data: [DONE]\n\n"
    finally:
        events.close()

@router.post("/api/chat/stream")
def chat_stream(body: StreamBody, user_id: str = Depends(require_user)):
    tid = storage.claim_thread(user_id, body.thread_id)
    if body.lecture_id:
        storage.lecture_content(user_id, body.lecture_id)
    return StreamingResponse(_sse(conversation_events(user_id, body.message, lecture_id=body.lecture_id, thread_id=tid)),
        media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

@router.get("/api/qa/lectures")
def lecture_choices(user_id: str = Depends(require_user)):
    data = storage.lectures(user_id)
    return pack(data, mock=all(item["mock"] for item in data["items"]))

@router.post("/api/qa/messages/{message_id}/feedback")
def answer_feedback(message_id: str, body: FeedbackBody, user_id: str = Depends(require_user)):
    return pack(storage.feedback(user_id, message_id, body.rating, body.reason), mock=False)
