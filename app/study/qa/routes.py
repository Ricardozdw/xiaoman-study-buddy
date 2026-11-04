"""问答线占位。底座 POST /api/chat 是一次性 JSON，这里另开 SSE。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.auth import require_user

router = APIRouter(tags=["问答"])


class StreamBody(BaseModel):
    message: str = ""
    lecture_id: str = ""
    thread_id: str = ""


def _chunks(text: str):
    step = 8
    for index in range(0, len(text), step):
        piece = text[index : index + step]
        yield f"data: {json.dumps({'delta': piece}, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


@router.post("/api/chat/stream")
def chat_stream(body: StreamBody, user_id: str = Depends(require_user)):
    """流式占位，不进入底座的草稿和记忆图。

    真实对话仍走底座 POST /api/chat。user_id 只用来确认已登录。
    """
    del user_id
    lecture = body.lecture_id or "最近一讲"
    text = (body.message or "").strip()
    if not text:
        reply = "先说一句你想问的。这是地基的模拟回复。"
    else:
        reply = (
            f"（模拟）我听到了：「{text[:80]}」。"
            f"若要对着资料问，用 @ 指定讲次（当前：{lecture}）。"
            "正式出处问答还没接上。"
        )
    return StreamingResponse(_chunks(reply), media_type="text/event-stream", headers={"Cache-Control": "no-store"})
