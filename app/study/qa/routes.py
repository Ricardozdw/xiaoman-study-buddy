"""问答线占位。底座 POST /api/chat 仍是一次性 JSON，这里另开 SSE。

TODO(问答线): 底座网关只有一次性 complete，没有逐 token 的流。
这里把整段文字切成小块再以 SSE 送出，页面可以边到边显示。
真正从模型一边生成一边吐字，要等网关有流式接口。不要改 POST /api/chat。
"""

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
    step = 2
    for index in range(0, len(text), step):
        piece = text[index : index + step]
        yield f"data: {json.dumps({'delta': piece}, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


def _reply(message: str, lecture_id: str, user_id: str) -> str:
    from app.agent.crisis_rules import has_crisis_signal
    from app.gateway.llm_gateway import chat_text, has_llm

    text = (message or "").strip()
    lecture = lecture_id or "最近一讲"
    if text and has_crisis_signal(text):
        # 危机识别留在底座对话里。这里不另写一套说法，改走底座的一次性对话再切块。
        from app.graph import run_action

        out = run_action({"user_id": user_id, "action": "chat", "message": text, "channel": "web"})
        messages = (out.get("state") or {}).get("messages") or []
        parts = [
            item.get("content")
            for item in messages
            if isinstance(item, dict) and item.get("role") == "assistant" and item.get("content")
        ]
        joined = "\n".join(str(part) for part in parts).strip()
        if joined:
            return joined
    if text and has_llm(task="chat"):
        # 有 key 时用网关拿整段，再切成 SSE。还不是模型的逐 token 流。
        produced = chat_text(
            "你是学习搭子小满。只用一两句回答。这是地基阶段，资料问答还没接上。",
            text,
            task="chat",
            fallback="",
            timeout=20,
        )
        if produced and produced.strip():
            return produced.strip()
    if not text:
        return "先说一句你想问的。这是地基的模拟回复。"
    return (
        f"（模拟）我听到了：「{text[:80]}」。"
        f"若要对着资料问，用 @ 指定讲次（当前：{lecture}）。"
        "正式出处问答还没接上。"
    )


@router.post("/api/chat/stream")
def chat_stream(body: StreamBody, user_id: str = Depends(require_user)):
    """把回复切成小块的 SSE。"""
    return StreamingResponse(
        _chunks(_reply(body.message, body.lecture_id, user_id)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
