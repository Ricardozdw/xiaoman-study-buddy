"""Versioned intent capability. Offline rules are explicitly marked as simulated."""
from __future__ import annotations

import json
import re
import time
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from app.data_access.session import SessionLocal
from app.gateway.llm_gateway import chat_json, has_llm
from app.study.common.bad_cases import write_bad_case
from app.study.common.db import ensure_schema
from app.study.common.models import LlmCall
from .safety import clean_text, prompt


class Intent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Literal["qa", "quiz", "plan", "chat"]


def _offline(text: str) -> str:
    if re.search(r"出.{0,4}题|考考我|练习一下|测验", text):
        return "quiz"
    if re.search(r"\d+\s*分钟|调整.*安排|调整.*计划|换.*强度|今天.*没空|今天.*时间|轻松一点|冲刺", text):
        return "plan"
    if re.fullmatch(r"[你好您好早晚安谢再见嗨哈呀啊！!，,。\s]+", text):
        return "chat"
    return "qa"


def classify(user_id: str, text: str) -> dict:
    ensure_schema()
    text = clean_text(user_id, text, 4000)
    system = prompt("qa.intent")
    user = "<source>" + json.dumps({"message": text}, ensure_ascii=False) + "</source>"
    offline = not has_llm(task="qa.intent")
    fallback = {"intent": _offline(text)}
    for attempt in range(2):
        started = time.perf_counter()
        raw = fallback if offline else chat_json(system, user, task="qa.intent", fallback={}, timeout=5, max_tokens=80)
        fields = {key: value for key, value in raw.items() if not key.startswith("_")} if isinstance(raw, dict) else {}
        try:
            parsed = Intent.model_validate(fields)
        except ValidationError:
            parsed = None
        with SessionLocal() as session:
            session.add(LlmCall(id=uuid.uuid4().hex, user_id=user_id, capability="理解用户想干嘛", prompt_name="qa.intent", prompt_version="v1",
                                model=str(raw.get("_model", "mock" if offline else "gateway"))[:128] if isinstance(raw, dict) else "gateway",
                                prompt_tokens=len(system) + len(user), completion_tokens=len(json.dumps(raw, ensure_ascii=False)),
                                estimated=1, latency_ms=int((time.perf_counter()-started)*1000), ok=int(parsed is not None)))
            session.commit()
        if parsed is not None:
            return {"intent": parsed.intent, "mock": offline or raw.get("_mode") == "mock"}
        write_bad_case(user_id=user_id, capability="理解用户想干嘛", input_payload={"message": text, "attempt": attempt + 1},
                       actual_output=clean_text(user_id, json.dumps(raw, ensure_ascii=False)), prompt_version="qa.intent@v1", problem_type="格式错", source="qa_intent")
        system += "\n上次格式不对，只返回包含 intent 的 JSON。"
    # Safe clarification, never dispatch a side effect from an invalid model label.
    return {"intent": "qa", "mock": False, "error": "intent_invalid"}
