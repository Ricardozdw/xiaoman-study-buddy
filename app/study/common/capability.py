"""一个完整的 AI 能力范例。其他线照这个接自己的提示词。

流程：读版本化提示词 → 经底座网关 → 校验 JSON → 不合格重试一次 →
仍失败则写 bad case。用量写入 llm_calls（带 user_id 和能力名）。
没配模型 key 时网关走离线占位，本函数仍记下估算 token。
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field, ValidationError

from app.data_access.session import SessionLocal
from app.gateway.config import ModelSpec
from app.gateway.llm_gateway import chat_json, has_llm
from app.gateway.usage import record as record_gateway_usage
from app.prompts import load_prompt
from app.study.common.bad_cases import write_bad_case
from app.study.common.db import ensure_schema
from app.study.common.models import LlmCall, _now
from app.tools.prompt_data import UNTRUSTED_DATA_RULE

PROMPT_NAME = "study.example"
PROMPT_VERSION = "v1"
CAPABILITY = "示范"
LABEL = "AI 整理，可以改"


class ExampleOutput(BaseModel):
    summary: str = Field(min_length=1)
    page: int
    label: str


def _system_prompt() -> str:
    return load_prompt(PROMPT_NAME, PROMPT_VERSION, untrusted_data_rule=UNTRUSTED_DATA_RULE)


def _fallback(page_text: str, page: int) -> dict[str, Any]:
    sentence = " ".join(page_text.split())
    sentence = sentence[:80] or "（离线占位）这一页没有可用的课文。"
    return {"summary": sentence, "page": page, "label": LABEL}


def _parse(raw: Any) -> Optional[ExampleOutput]:
    if not isinstance(raw, dict):
        return None
    data = {key: value for key, value in raw.items() if not str(key).startswith("_")}
    try:
        out = ExampleOutput.model_validate(data)
    except ValidationError:
        return None
    if out.label != LABEL:
        return None
    return out


def _estimate_tokens(text: str) -> int:
    return max(1, len(text or ""))


def _record(
    *,
    user_id: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
    ok: bool,
    offline: bool,
) -> None:
    ensure_schema()
    with SessionLocal() as session:
        session.add(
            LlmCall(
                id=uuid.uuid4().hex,
                user_id=user_id,
                capability=CAPABILITY,
                prompt_name=PROMPT_NAME,
                prompt_version=PROMPT_VERSION,
                model=model[:128],
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                ok=1 if ok else 0,
                estimated=1,
                created_at=_now(),
            )
        )
        session.commit()
    if offline:
        # 网关在没 key 时不会写用量环。这里补一条，方便在 /api/llm/usage 里看到。
        record_gateway_usage(
            request_id=uuid.uuid4().hex[:12],
            task="study.example",
            tier="fast",
            spec=ModelSpec(id="study-example-offline", model=model or "mock", vendor="offline"),
            attempt=1,
            ok=ok,
            latency_ms=float(latency_ms),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )


def run_example(
    user_id: str,
    page_text: str,
    *,
    page: int = 1,
    demo_failure: bool = False,
) -> dict[str, Any]:
    """跑示范能力。demo_failure 只给地基自检：故意两次不合格并写一条测试 bad case。"""
    text = (page_text or "").strip()[:4000]
    page_no = page if page > 0 else 1
    system = _system_prompt()
    user = f"<source>\n第 {page_no} 页\n{text}\n</source>"
    offline = not has_llm(task=PROMPT_NAME)
    last: Any = None
    started = time.perf_counter()
    for attempt in range(2):
        t0 = time.perf_counter()
        if demo_failure:
            raw: Any = {"unexpected": True, "attempt": attempt + 1}
            model = "foundation-demo"
        else:
            raw = chat_json(
                system,
                user,
                fallback=_fallback(text, page_no),
                task=PROMPT_NAME,
                timeout=20,
                max_tokens=400,
            )
            model = str(raw.get("_model") or ("mock" if offline else ""))
        latency_ms = int((time.perf_counter() - t0) * 1000)
        parsed = _parse(raw)
        rendered = json.dumps(raw, ensure_ascii=False) if isinstance(raw, dict) else str(raw)
        _record(
            user_id=user_id,
            model=model,
            prompt_tokens=_estimate_tokens(system) + _estimate_tokens(user),
            completion_tokens=_estimate_tokens(rendered),
            latency_ms=latency_ms,
            ok=parsed is not None,
            offline=offline or demo_failure,
        )
        if parsed is not None:
            return {
                "ok": True,
                "mock": offline or bool(raw.get("_mode") == "mock") or demo_failure,
                "summary": parsed.summary,
                "page": parsed.page,
                "label": parsed.label,
                "mode": "mock" if offline else str(raw.get("_mode") or "live"),
                "model": model,
                "prompt": f"{PROMPT_NAME}@{PROMPT_VERSION}",
                "attempts": attempt + 1,
                "bad_case_id": None,
            }
        last = raw
        system += "\n上次输出未通过格式校验。请重新输出完整 JSON，字段只有 summary、page、label。"
    bad_id = write_bad_case(
        user_id=user_id,
        capability=CAPABILITY,
        input_payload={"page": page_no, "text": text, "demo_failure": demo_failure},
        actual_output=json.dumps(last, ensure_ascii=False) if isinstance(last, dict) else str(last),
        expected_output=json.dumps(_fallback(text, page_no), ensure_ascii=False),
        model="foundation-demo" if demo_failure else "unknown",
        prompt_version=f"{PROMPT_NAME}@{PROMPT_VERSION}",
        problem_type="格式错",
        severity="低",
        source="foundation_demo" if demo_failure else "backend",
        fix_note="地基自检写入，不是真实用户的错题。" if demo_failure else "JSON 校验两次都没过。",
    )
    return {
        "ok": False,
        "mock": True,
        "summary": "",
        "page": page_no,
        "label": LABEL,
        "mode": "mock" if offline or demo_failure else "live",
        "model": "foundation-demo" if demo_failure else "",
        "prompt": f"{PROMPT_NAME}@{PROMPT_VERSION}",
        "attempts": 2,
        "bad_case_id": bad_id,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "message": "输出不合格，已重试一次并写入 bad case。",
    }
