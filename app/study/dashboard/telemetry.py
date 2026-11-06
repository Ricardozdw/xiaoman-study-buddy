"""各线可选用的统一入口。不修改底座网关或其他线的调用。"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
import uuid

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.data_access.session import SessionLocal
from app.gateway import core
from app.prompts import load_prompt
from app.study.common.bad_cases import write_bad_case
from app.study.common.db import ensure_schema
from app.study.common.models import BadCase, LlmCall, Question, StudyMessage
from app.tools.prompt_data import UNTRUSTED_DATA_RULE


def record_call(*, user_id: str, capability: str, prompt_name: str, prompt_version: str,
                model: str, prompt_tokens: int | None, completion_tokens: int | None,
                latency_ms: float, ok: bool, estimated: bool = False) -> str:
    ensure_schema()
    if not user_id or not capability or not prompt_name or not prompt_version:
        raise ValueError("身份、能力、提示词名称和版本必填")
    if any(v is not None and (isinstance(v, bool) or not isinstance(v, int) or v < 0)
           for v in (prompt_tokens, completion_tokens)):
        raise ValueError("token 必须是非负整数，未知时填 None")
    if isinstance(latency_ms, bool) or not isinstance(latency_ms, (int, float)) or not math.isfinite(latency_ms) or latency_ms < 0:
        raise ValueError("延迟必须是有限的非负数")
    row_id = uuid.uuid4().hex
    with SessionLocal() as session:
        session.add(LlmCall(
            id=row_id, user_id=user_id, capability=capability[:64], prompt_name=prompt_name[:64],
            prompt_version=prompt_version[:16], model=model[:128],
            prompt_tokens=prompt_tokens or 0, completion_tokens=completion_tokens or 0,
            latency_ms=max(0, round(latency_ms)), ok=int(ok),
            estimated=int(estimated or prompt_tokens is None or completion_tokens is None),
        ))
        session.commit()
    return row_id


def tracked_json(*, user_id: str, capability: str, prompt_name: str, prompt_version: str,
                 payload: dict, response_model: type[BaseModel], tier: str = "fast") -> BaseModel:
    """经原网关调用；每次上游尝试单独记账，校验与重试仍由网关负责。

    无 key 时明确失败，不把预期答案当模拟回复交付。公开样例资料才允许传入。
    """
    from app.gateway.llm_gateway import _mask_sandbox
    system = load_prompt(prompt_name, prompt_version, untrusted_data_rule=UNTRUSTED_DATA_RULE)
    system += "\n仅输出符合以下 JSON Schema 的对象：\n" + json.dumps(response_model.model_json_schema(), ensure_ascii=False)
    system, user = _mask_sandbox(system, json.dumps(payload, ensure_ascii=False))
    result = core.complete(system, user, tier=tier, task=prompt_name, kind="json",
                           temperature=0, max_tokens=2000, timeout=30, response_model=response_model)
    for attempt in result.attempts:
        record_call(
            user_id=user_id, capability=capability, prompt_name=prompt_name, prompt_version=prompt_version,
            model=str(attempt["model"]), prompt_tokens=attempt.get("prompt_tokens"),
            completion_tokens=attempt.get("completion_tokens"), latency_ms=attempt["latency_ms"], ok=bool(attempt["ok"]),
        )
        if not attempt["ok"]:
            write_bad_case(user_id=user_id, capability=capability, input_payload=payload,
                           actual_output="网关尝试失败：" + str(attempt.get("error") or "unknown"),
                           model=str(attempt["model"]), prompt_version=f"{prompt_name}@{prompt_version}",
                           problem_type="格式错" if attempt.get("error") == "schema" else "报错或超时",
                           severity="中", fix_note="该次失败后网关可能继续重试或切备用；上游失败时可能无输出。")
    if not result.ok:
        if result.mode != "mock" and not result.attempts:
            write_bad_case(user_id=user_id, capability=capability, input_payload=payload,
                           actual_output="网关调用失败", model=result.spec.model if result.spec else "unknown",
                           prompt_version=f"{prompt_name}@{prompt_version}", problem_type="报错或超时",
                           severity="中", fix_note="重试与备用模型仍未成功；请查看服务端网关日志。")
        raise RuntimeError("模型未配置" if result.mode == "mock" else "模型调用失败，已记录 bad case")
    try:
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", result.content.strip(), flags=re.I)
        return response_model.model_validate_json(content)
    except ValueError:
        write_bad_case(user_id=user_id, capability=capability, input_payload=payload,
                       actual_output=result.content, model=result.spec.model if result.spec else "unknown",
                       prompt_version=f"{prompt_name}@{prompt_version}", problem_type="格式错", severity="中")
        raise


def usage_summary(user_id: str) -> dict:
    ensure_schema()
    pricing = json.loads(Path(__file__).with_name("prices.json").read_text())
    with SessionLocal() as session:
        rows = session.scalars(select(LlmCall).where(LlmCall.user_id == user_id).order_by(LlmCall.created_at, LlmCall.id)).all()
        buckets: dict[tuple, dict] = {}
        legacy: dict[str, dict] = {}
        totals: dict[str, float] = {}
        for row in rows:
            price = pricing["models"].get(row.model)
            currency = price["currency"] if price else None
            # Unknown upstream tokens do not become a zero-cost call.
            cost = round((row.prompt_tokens * price["input_per_million"] + row.completion_tokens * price["output_per_million"]) / 1_000_000, 8) if price and not row.estimated else None
            key = (row.capability, row.model, currency)
            bucket = buckets.setdefault(key, {
                "user_id": user_id, "capability": row.capability, "model": row.model, "currency": currency,
                "calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "estimated_calls": 0,
                "unpriced_calls": 0, "priced_cost_estimate": 0.0,
            })
            bucket["calls"] += 1
            bucket["prompt_tokens"] += row.prompt_tokens
            bucket["completion_tokens"] += row.completion_tokens
            bucket["estimated_calls"] += int(bool(row.estimated))
            bucket["unpriced_calls"] += int(cost is None)
            if cost is not None:
                bucket["priced_cost_estimate"] = round(bucket["priced_cost_estimate"] + cost, 8)
                totals[currency] = round(totals.get(currency, 0) + cost, 8)
            cap = legacy.setdefault(row.capability, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
            for field in cap:
                cap[field] += 1 if field == "calls" else getattr(row, field)
        for bucket in buckets.values():
            bucket["cost_complete"] = bucket["unpriced_calls"] == 0
            bucket["complete_cost_estimate"] = bucket["priced_cost_estimate"] if bucket["cost_complete"] else None
        return {"by_capability": legacy, "groups": list(buckets.values()), "totals_by_currency": totals,
                "cost_complete": all(bucket["cost_complete"] for bucket in buckets.values()),
                "pricing": pricing, "note": "费用为指定价格表的估算，不是实际账单。未知单价或估算 token 的调用不计入费用小计。",
                "items": [{"id": r.id, "capability": r.capability, "model": r.model,
                           "prompt": f"{r.prompt_name}@{r.prompt_version}", "prompt_tokens": r.prompt_tokens,
                           "completion_tokens": r.completion_tokens, "estimated": bool(r.estimated),
                           "ok": bool(r.ok), "created_at": r.created_at} for r in rows[-20:]]}


def capture_feedback(user_id: str, *, target_type: str, target_id: str, reason: str) -> str | None:
    if target_type not in ("message", "question"):
        raise ValueError("反馈目标必须是 message 或 question")
    ensure_schema()
    model_cls = StudyMessage if target_type == "message" else Question
    with SessionLocal() as session:
        row = session.scalar(select(model_cls).where(model_cls.id == target_id, model_cls.user_id == user_id))
        if row is None:
            return None
        case_id = hashlib.sha256(f"{user_id}:{target_type}:{target_id}:down".encode()).hexdigest()
        existing = session.scalar(select(BadCase).where(BadCase.id == case_id, BadCase.user_id == user_id))
        if existing:
            # A thumb-down is often followed by an optional reason. Keep one
            # incident while allowing the first explanation to be filled in.
            try:
                original_input = json.loads(existing.input_json)
            except ValueError:
                original_input = None
            if reason and isinstance(original_input, dict) and not original_input.get("reason"):
                original_input["reason"] = reason[:1000]
                existing.input_json = json.dumps(original_input, ensure_ascii=False)
                session.commit()
            return case_id
        if target_type == "message":
            try:
                refs = json.loads(row.refs_json or "[]")
            except ValueError:
                refs = []
            metadata = refs if isinstance(refs, dict) else {}
            actual = row.content
            payload = {"target_type": target_type, "target_id": target_id, "refs": refs, "reason": reason}
            capability, problem = "问答", "用户反馈"
            row.feedback = "down"
        else:
            metadata = {}
            actual = json.dumps({"stem": row.stem, "options": row.options_json, "answer": row.answer, "analysis": row.analysis}, ensure_ascii=False)
            payload = {"target_type": target_type, "target_id": target_id, "lecture_id": row.lecture_id, "source": row.source_json, "reason": reason}
            capability, problem = "出题", "题目有误"
        session.add(BadCase(id=case_id, user_id=user_id, capability=capability,
                            input_json=json.dumps(payload, ensure_ascii=False), actual_output=actual,
                            model=str(metadata.get("model") or "not_recorded")[:128],
                            prompt_version=str(metadata.get("prompt_version") or "not_recorded")[:32],
                            problem_type=problem, severity="中", status="新", source="user_feedback",
                            fix_note="原始生成来源尚未留档" if not metadata else ""))
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            if session.scalar(select(BadCase.id).where(BadCase.id == case_id, BadCase.user_id == user_id)) is None:
                raise
        return case_id
