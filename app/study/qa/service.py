"""Validate each generated sentence before exposing it over SSE."""
from __future__ import annotations

import json
import re
import time
import uuid
from contextlib import closing
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from fastapi import HTTPException
from app.agent.crisis_rules import has_crisis_signal
from app.agent.harness.guardrails import guard_outbound_text
from app.data_access import user_scope
from app.privacy import privacy_reply, redact_sensitive, suggest_secret_key
from app.study.common.bad_cases import write_bad_case
from . import adapters, storage
from .intents import classify
from .model_stream import StreamError, stream_text
from .safety import clean_text, clean_payload, prompt

LABEL = "AI 整理，可以改"
DISCLOSURE = "你的资料里没提到，下面是通用知识。\n"
_PAGE_TAG = re.compile(r"【[^】]*第\s*\d+\s*页[^】]*】|\[第\s*\d+\s*页\]")

class Reference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    page: int = Field(gt=0)
    quote: str = Field(min_length=1, max_length=2000)

class Sentence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["sentence"]
    text: str = Field(min_length=1, max_length=3000)
    references: list[Reference] = Field(max_length=8)

class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["scope"]
    in_material: bool


def _bad(user_id, message, output, kind="格式错", **context):
    try:
        safe = clean_text(user_id, str(output))
        payload = clean_payload(user_id, {"message": message, **context})
    except HTTPException:
        safe, payload = "privacy_unavailable", {"message": "[安全检查不可用，原文未保存]"}
    return write_bad_case(user_id=user_id, capability="问答", input_payload=payload,
        actual_output=safe, prompt_version="qa.answer@v1", problem_type=kind, source="qa_backend")


def _guard(text, user, question):
    return guard_outbound_text(text, user_id=user, inputs=(question,))


def _verified(sentence, pages, lecture, user, question, grounded):
    by_page = {p["page"]: p["text"] for p in pages}
    refs, rejected = [], []
    for ref in sentence.references:
        if not grounded or not ref.quote.strip() or ref.quote not in by_page.get(ref.page, "") or _guard(ref.quote, user, question) != ref.quote:
            rejected.append(ref.model_dump())
        else:
            item = {"lecture_id": lecture, "page": ref.page, "quote": ref.quote}
            if item not in refs:
                refs.append(item)
    text = _PAGE_TAG.sub("", sentence.text).strip()
    guarded = _guard(text, user, question)
    if guarded != text:
        refs = []
    markers = "".join(f"【第 {ref['page']} 页】" for ref in refs)
    return guarded + markers + "\n", refs, rejected


def _json_lines(chunks, state, user_id, question):
    buffer = ""
    for chunk in chunks:
        if chunk.get("type") == "usage":
            if chunk.get("ok") is False and not chunk.get("mock"):
                _bad(user_id, question, chunk.get("error", "upstream_failed"), "调用失败", model=chunk.get("model", ""))
            state["mock"] |= bool(chunk.get("mock"))
            state["model"] = chunk.get("model", "")
            state["offline"] |= bool(chunk.get("mock"))
            continue
        buffer += chunk.get("delta", "")
        if len(buffer) > 30000:
            raise ValueError("oversized JSON line")
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            if line.strip():
                yield json.loads(line)
    if buffer.strip():
        yield json.loads(buffer)


def _qa_events(user_id, question, lecture_id, state):
    lecture, pages, sample = storage.lecture_content(user_id, lecture_id)
    state["lecture_id"], state["mock"] = lecture, state["mock"] or sample
    system = prompt("qa.answer")
    if sum(len(p["text"]) for p in pages) > 120000:
        raise StreamError("material_too_long")
    safe_pages = [{"page": p["page"], "text": clean_text(user_id, p["text"], 200000)} for p in pages]
    source = "<source>" + json.dumps({"question": question, "pages": safe_pages}, ensure_ascii=False) + "</source>"
    for attempt in range(2):
        scope, count = None, 0
        state["offline"] = False
        try:
            with closing(stream_text(system, source, task="qa.answer", user_id=user_id, prompt_version="v1")) as chunks:
                for raw in _json_lines(chunks, state, user_id, question):
                    if scope is None:
                        scope = Scope.model_validate(raw)
                        state["in_material"] = scope.in_material
                        if not scope.in_material:
                            yield {"delta": DISCLOSURE}
                        continue
                    sentence = Sentence.model_validate(raw)
                    count += 1
                    if count > 8:
                        raise ValueError("too many sentences")
                    text, refs, rejected = _verified(sentence, pages, lecture, user_id, question, scope.in_material)
                    state["citation_failures"] += len(rejected)
                    if rejected:
                        _bad(user_id, question, rejected, "出处错", lecture_id=lecture)
                    state["references"].extend(refs)
                    yield {"delta": text}
                    yield {"type": "references", "references": state["references"].copy()}
            if state["offline"] and scope is None:
                state["in_material"] = None
                quote = pages[0]["text"][:180]
                sentence = Sentence(type="sentence", text="（模拟）尚未配置模型。以下是这讲原文示例：" + quote,
                    references=[Reference(page=pages[0]["page"], quote=quote)])
                text, refs, _ = _verified(sentence, pages, lecture, user_id, question, True)
                state["references"] = refs
                yield {"delta": text}
                yield {"type": "references", "references": refs}
                return
            if scope is None or count == 0:
                raise ValueError("missing answer")
            return
        except (ValueError, ValidationError) as exc:
            _bad(user_id, question, type(exc).__name__, lecture_id=lecture, attempt=attempt + 1)
            if state["text"] or attempt:
                raise StreamError("invalid_output") from exc
            system += "\n上次格式未通过校验。重新输出 scope 行，之后至少一个 sentence 行；每行完整 JSON。"


def _base_reply(user_id, text, thread_id):
    from app.main import ChatRequest, chat
    response = chat(ChatRequest(user_id=user_id, message=text, thread_id=thread_id))
    messages = response.data.get("messages") or []
    return next((str(m["content"]) for m in reversed(messages) if m.get("role") == "assistant" and m.get("content")), "我在，想聊点什么？")


def _conversation_events(user_id: str, message: str, *, lecture_id: str = "", thread_id: str = ""):
    started = time.perf_counter()
    state = {"text": "", "references": [], "mock": False, "in_material": None, "citation_failures": 0,
        "first_text_ms": None, "ok": False, "model": "", "lecture_id": lecture_id}
    message_id = uuid.uuid4().hex
    thread_id = storage.claim_thread(user_id, thread_id)
    safe_message = "[输入未保存]"
    intent, error_code = "chat", ""
    try:
        redacted, private = redact_sensitive(message)
        safe_message = clean_text(user_id, redacted, 4000)
        crisis = has_crisis_signal(safe_message)
        from app.study.v2 import goal_flow
        pending_goal = goal_flow.pending(user_id) if (not private and not crisis) else None
        if pending_goal is not None:
            result = {"intent": "goal", "goal": pending_goal["title"], "mock": False}
        else:
            result = {"intent": "chat", "mock": False} if private or crisis else classify(user_id, safe_message)
        intent = result["intent"]
        # The plan owner currently labels upstream study fixtures as simulated.
        state["mock"] = result.get("mock", False) or intent == "plan"
        if intent in ("qa", "quiz") and not private and not crisis:
            chosen, _, sample = storage.lecture_content(user_id, lecture_id)
            state["lecture_id"], state["mock"] = chosen, state["mock"] or sample
        yield {"type": "meta", "message_id": message_id, "thread_id": thread_id, "intent": intent,
            "lecture_id": state["lecture_id"], "mock": state["mock"], "label": LABEL}

        def events():
            if private:
                yield {"delta": privacy_reply(suggest_secret_key(safe_message, private))}
            elif crisis or intent == "chat":
                yield {"delta": _base_reply(user_id, safe_message, thread_id)}
            elif result.get("error"):
                raise StreamError(result["error"])
            elif intent == "quiz":
                data = adapters.practice_request(user_id, safe_message, state["lecture_id"])
                state["mock"] |= data.get("mock", True)
                yield {"delta": "（模拟）已转到练习线，下面是按这一讲资料出的模拟题。" if state["mock"] else "已经为你打开练习。"}
                yield {"type": "handoff", "intent": "quiz", "data": data}
            elif intent == "plan":
                data = adapters.plan_request(user_id, safe_message)
                state["mock"] |= data.get("mock", True)
                reply = data.get("reply") or "这里有一个安排建议，确认后才会生效。"
                yield {"delta": ("（模拟）" if state["mock"] else "") + reply}
                if data.get("card") is not None:
                    yield {"type": "handoff", "intent": "plan", "data": data}
            elif intent == "goal":
                if pending_goal is not None:
                    next_q, outline = goal_flow.advance(user_id, safe_message)
                    if outline is not None:
                        yield {"delta": f"好，我按「{pending_goal['title']}」排好学习大纲了，可以直接改或确认。"}
                        yield {"type": "handoff", "intent": "goal", "data": {"outline": outline}}
                    elif next_q is not None:
                        yield {"delta": next_q["question"]}
                        yield {"type": "handoff", "intent": "goal", "data": next_q}
                else:
                    from app.study.plan import goal as goal_mod
                    goal_type = result.get("goal_type", "skill")
                    goal_name = (result.get("goal") or safe_message).strip()[:20]
                    try:
                        current = goal_mod.current(user_id)
                        needs_setup = bool(current.get("needs_setup", True))
                        existing_title = current.get("title") or ""
                    except Exception:
                        needs_setup, existing_title = True, ""
                    if needs_setup:
                        first = goal_flow.start(user_id, goal_type, goal_name, safe_message)
                        yield {"delta": first["question"]}
                        yield {"type": "handoff", "intent": "goal", "data": first}
                    else:
                        yield {"delta": f"你现在学的是「{existing_title}」，要改成「{goal_name}」吗？"}
            else:
                yield from _qa_events(user_id, safe_message, state["lecture_id"], state)

        with closing(events()) as iterator:
            for event in iterator:
                if event.get("delta"):
                    if state["first_text_ms"] is None:
                        state["first_text_ms"] = int((time.perf_counter() - started) * 1000)
                    state["text"] += event["delta"]
                yield event
        state["ok"] = True
    except GeneratorExit:
        error_code = "cancelled"
        raise
    except Exception as exc:
        error_code = exc.code if isinstance(exc, StreamError) else "qa_unavailable"
        _bad(user_id, safe_message, error_code, "调用失败", lecture_id=state["lecture_id"])
        yield {"type": "error", "code": error_code, "message": "这次回答没有完成，请稍后重试。"}
    finally:
        storage.save_answer(user_id, message_id, state["text"], state["references"],
            {"question": safe_message, "thread_id": thread_id, "lecture_id": state["lecture_id"], "intent": intent,
             "model": state["model"], "mock": state["mock"], "ok": state["ok"], "error": error_code})
    yield {"type": "complete", "message_id": message_id, "ok": state["ok"], "mock": state["mock"],
        "in_material": state["in_material"], "citation_failures": state["citation_failures"], "first_text_ms": state["first_text_ms"]}


def conversation_events(user_id: str, message: str, *, lecture_id: str = "", thread_id: str = ""):
    """Establish identity per next(), since Starlette resumes sync SSE in fresh contexts."""
    events = _conversation_events(user_id, message, lecture_id=lecture_id, thread_id=thread_id)
    try:
        while True:
            with user_scope(user_id):
                try:
                    event = next(events)
                except StopIteration:
                    return
            yield event
    finally:
        with user_scope(user_id):
            events.close()
