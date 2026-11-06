"""Generate source-checked notes through the existing model gateway.

There is no runtime mock success: missing configuration, provider fallback,
invalid output, or an unavailable outbound guard leaves the source reusable
and raises a public MaterialError. Tests may use the gateway's test seam.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
import unicodedata
import uuid
from contextlib import nullcontext
from functools import lru_cache
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from app.agent.harness import context as trace_context
from app.agent.harness.guardrails import guard_text
from app.agent.harness.leak import register_allowed_output, register_system_prompt
from app.data_access.session import SessionLocal
from app.gateway.llm_gateway import chat_json, has_llm
from app.prompts import load_prompt
from app.study.common.bad_cases import write_bad_case
from app.study.common.db import ensure_schema
from app.study.common.models import LlmCall, _now
from app.study.materials.errors import MaterialError
from app.tools.prompt_data import UNTRUSTED_DATA_RULE, data_block

PROMPT_NAME = "materials.summary"
PROMPT_VERSION = "v3"
CAPABILITY = "学习文档"
LABEL = "AI 整理，可以改"
MAX_SOURCE_CHARACTERS = 100_000
MAX_SOURCE_PAGES = 200
GENERATION_BUDGET_SECONDS = 110.0
MAX_OUTPUT_TOKENS = 6500
_clock = time.monotonic

Title = Annotated[str, StringConstraints(strip_whitespace=True, max_length=160)]
ItemName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
ItemText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
Quote = Annotated[str, StringConstraints(strip_whitespace=True, min_length=4, max_length=240)]
PageNumber = Annotated[int, Field(strict=True, ge=1, le=MAX_SOURCE_PAGES)]


class _StrictOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SummaryItem(_StrictOutput):
    text: ItemText
    page: PageNumber
    quote: Quote


class KnowledgePointItem(_StrictOutput):
    name: ItemName
    explanation: ItemText
    page: PageNumber
    quote: Quote


class TermItem(_StrictOutput):
    term: ItemName
    definition: ItemText
    page: PageNumber
    quote: Quote


class NoteOutput(_StrictOutput):
    title: Title = ""
    summaries: list[SummaryItem] = Field(min_length=3, max_length=3)
    knowledge_points: list[KnowledgePointItem] = Field(min_length=1, max_length=20)
    terms: list[TermItem] = Field(max_length=20)


EvidenceId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class GeneratedSummaryItem(_StrictOutput):
    text: ItemText
    evidence_id: EvidenceId


class GeneratedKnowledgePoint(_StrictOutput):
    name: ItemName
    explanation: ItemText
    evidence_id: EvidenceId


class GeneratedTerm(_StrictOutput):
    term: ItemName
    definition: ItemText
    evidence_id: EvidenceId


class GeneratedNoteOutput(_StrictOutput):
    title: Title = ""
    summaries: list[GeneratedSummaryItem] = Field(min_length=3, max_length=3)
    knowledge_points: list[GeneratedKnowledgePoint] = Field(min_length=1, max_length=20)
    terms: list[GeneratedTerm] = Field(max_length=20)


class _OutputIssue(ValueError):
    def __init__(self, reason: str, kind: str = "schema"):
        super().__init__(reason)
        self.reason = reason
        self.kind = kind


@lru_cache(maxsize=1)
def _system_prompt() -> str:
    contract = json.dumps(GeneratedNoteOutput.model_json_schema(), ensure_ascii=False)
    text = load_prompt(PROMPT_NAME, PROMPT_VERSION, untrusted_data_rule=UNTRUSTED_DATA_RULE,
                       output_contract=contract)
    # Schema field names are intentionally public; private instructions are not.
    register_allowed_output(contract)
    register_allowed_output(json.dumps(NoteOutput.model_json_schema(), ensure_ascii=False))
    register_system_prompt(PROMPT_NAME, text)
    return text


def normalize_source(text: str) -> str:
    """Ignore PDF line wrapping and Unicode presentation variants, not words."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def validate_note_output(raw: Any, pages: list[dict]) -> dict[str, Any]:
    """Validate structure and each claimed quote; also usable by note storage."""
    if not isinstance(raw, dict):
        raise _OutputIssue("输出必须是一个 JSON 对象")
    payload = {key: value for key, value in raw.items() if not str(key).startswith("_")}
    try:
        validated = NoteOutput.model_validate(payload).model_dump()
    except ValidationError as error:
        # Field locations and types are sufficient; never echo model input.
        issues = "; ".join(
            f"{'.'.join(map(str, item['loc'])) or '$'}: {item['type']}"
            for item in error.errors(include_input=False, include_url=False)[:8]
        )
        raise _OutputIssue(f"JSON 字段未通过检查：{issues}") from None
    sources = {page["page"]: normalize_source(page["text"]) for page in pages}
    for group in ("summaries", "knowledge_points", "terms"):
        for index, item in enumerate(validated[group]):
            page = item["page"]
            quote = normalize_source(item["quote"])
            if page not in sources or len(quote) < 4 or quote not in sources[page]:
                raise _OutputIssue(f"{group}[{index}] 的页码或连续原句与资料不符", "citation")
    names = [normalize_source(item["name"]).casefold() for item in validated["knowledge_points"]]
    if len(names) != len(set(names)):
        raise _OutputIssue("知识点名称不能重复")
    terms = [normalize_source(item["term"]).casefold() for item in validated["terms"]]
    if len(terms) != len(set(terms)):
        raise _OutputIssue("术语名称不能重复")
    return validated


def _prepare_pages(pages: list[dict]) -> tuple[list[dict[str, Any]], str]:
    if not isinstance(pages, list) or not pages or len(pages) > MAX_SOURCE_PAGES:
        raise MaterialError("notes_source_invalid", "课件正文尚不可用，请先完成 PDF 读取", 422)
    canonical = []
    for index, page in enumerate(pages, 1):
        if (not isinstance(page, dict) or type(page.get("page")) is not int
                or page["page"] != index or not isinstance(page.get("text"), str)
                or page.get("mock") is True):
            raise MaterialError("notes_source_invalid", "课件正文或页码不完整，请重新读取 PDF", 422)
        canonical.append({"page": index, "text": page["text"]})
    if sum(len(page["text"]) for page in canonical) > MAX_SOURCE_CHARACTERS:
        raise MaterialError("notes_source_too_large", "这一讲文字过多，请把 PDF 按讲拆分后再整理", 422)
    if not any(page["text"].strip() for page in canonical):
        raise MaterialError("notes_source_invalid", "没有可整理的文字，请上传文字版 PDF", 422)
    serialized = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"))
    return canonical, hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def source_hash(pages: list[dict]) -> str:
    """Stable fingerprint of exact physical page numbers and source text."""
    return _prepare_pages(pages)[1]


def build_evidence(pages: list[dict]) -> tuple[list[dict], dict[str, dict]]:
    """Label the entire source, without asking a model to retype its symbols.

    Concatenating each page's passages exactly reconstructs its text. Every
    citeable map value is an unchanged, contiguous excerpt of that one page;
    whitespace-only or very short pieces remain in the source but get no ID.
    IDs include the document hash, so a reference from another source fails.
    """
    canonical, digest = _prepare_pages(pages)
    catalogue, evidence = [], {}
    width = 180
    for page in canonical:
        text, start, passages = page["text"], 0, []
        while start < len(text):
            end = min(start + width, len(text))
            if end < len(text):
                # Prefer a nearby physical line/word boundary, keeping all
                # separating characters inside the fragment, not discarding it.
                lower = start + width // 2
                boundary = text.rfind("\n", lower, end)
                if boundary < 0:
                    boundary = text.rfind(" ", lower, end)
                if boundary >= lower:
                    end = boundary + 1
            fragment = text[start:end]
            quote = fragment.strip()
            evidence_id = None
            if len(quote) >= 4 and len(normalize_source(quote)) >= 4:
                evidence_id = f"{digest[:10]}-p{page['page']:03d}-s{len(passages) + 1:03d}"
                evidence[evidence_id] = {"page": page["page"], "quote": quote}
            passages.append({"evidence_id": evidence_id, "text": fragment})
            start = end
        catalogue.append({"page": page["page"], "passages": passages})
    return catalogue, evidence


def resolve_evidence_output(raw: Any, evidence: dict[str, dict]) -> dict[str, Any]:
    """Turn only current-source IDs into trusted public page/quote fields."""
    if not isinstance(raw, dict):
        raise _OutputIssue("输出必须是一个 JSON 对象")
    payload = {key: value for key, value in raw.items() if not str(key).startswith("_")}
    try:
        checked = GeneratedNoteOutput.model_validate(payload).model_dump()
    except ValidationError as error:
        issues = "; ".join(
            f"{'.'.join(map(str, item['loc'])) or '$'}: {item['type']}"
            for item in error.errors(include_input=False, include_url=False)[:8]
        )
        raise _OutputIssue(f"JSON 字段未通过检查：{issues}") from None
    for group in ("summaries", "knowledge_points", "terms"):
        for index, item in enumerate(checked[group]):
            evidence_id = item.pop("evidence_id")
            if evidence_id not in evidence:
                raise _OutputIssue(f"{group}[{index}] 的原文片段编号不属于本份资料，请从 source 选择现有 evidence_id", "citation")
            item.update(evidence[evidence_id])
    return checked


def validate_note_content(content: dict, pages: list[dict]) -> dict[str, Any]:
    """Validate editable rich note content, returning only canonical fields.

    Server metadata and knowledge-point IDs are owned by persistence, not by
    the model or editable text. They are intentionally absent from the result.
    """
    canonical, _ = _prepare_pages(pages)
    if not isinstance(content, dict):
        raise MaterialError("notes_validation_failed", "学习笔记格式不正确，尚未保存修改", 422)
    known = {"title", "summaries", "knowledge_points", "terms"}
    metadata = {"schema_version", "file_id", "generation", "points", "source_hash", "label", "edited_by_user"}
    if set(content) - known - metadata:
        raise MaterialError("notes_validation_failed", "学习笔记包含不支持的字段，尚未保存修改", 422)
    payload = {key: value for key, value in content.items() if key in known}
    if isinstance(payload.get("knowledge_points"), list):
        payload["knowledge_points"] = [
            {key: value for key, value in item.items() if key != "id"} if isinstance(item, dict) else item
            for item in payload["knowledge_points"]
        ]
    try:
        return validate_note_output(payload, canonical)
    except _OutputIssue:
        raise MaterialError("notes_validation_failed", "笔记格式或出处不正确，尚未保存修改", 422) from None


validate_notes = validate_note_content


def _record_call(user_id: str, *, raw: Any, call: dict, system: str, source: str,
                 latency_ms: int, ok: bool) -> str:
    metadata = raw if isinstance(raw, dict) else {}
    model = str(call.get("actual_model") or call.get("model") or metadata.get("_model") or "unknown")
    usage = call.get("usage")
    reported = (isinstance(usage, dict)
                and type(usage.get("prompt_tokens")) is int and usage["prompt_tokens"] >= 0
                and type(usage.get("completion_tokens")) is int and usage["completion_tokens"] >= 0)
    rendered = json.dumps(raw, ensure_ascii=False, default=str)
    prompt_tokens = usage["prompt_tokens"] if reported else max(1, len(system) + len(source))
    completion_tokens = usage["completion_tokens"] if reported else max(1, len(rendered))
    ensure_schema()
    with SessionLocal() as session:
        session.add(LlmCall(
            id=uuid.uuid4().hex, user_id=user_id, capability=CAPABILITY,
            prompt_name=PROMPT_NAME, prompt_version=PROMPT_VERSION, model=model[:128],
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            latency_ms=max(0, latency_ms), ok=int(ok), estimated=int(not reported), created_at=_now(),
        ))
        session.commit()
    return model


def _provider_unavailable(raw: Any, call: dict) -> bool:
    metadata = raw if isinstance(raw, dict) else {}
    mode = str(call.get("mode") or metadata.get("_mode") or "")
    return (mode in ("mock", "mock_fallback") or bool(metadata.get("_model_error"))
            or (bool(metadata.get("_materials_unavailable")) and not metadata.get("_parse"))
            or (bool(call.get("fallback_reason")) and not metadata.get("_parse")))


def _safe_actual_output(raw: Any, *, user_id: str, source: str) -> str:
    # Failed provider messages/trace metadata never belong in a public bad case.
    if isinstance(raw, dict):
        raw = {key: value for key, value in raw.items() if not str(key).startswith("_")}
    rendered = json.dumps(raw, ensure_ascii=False, default=str)
    return guard_text(rendered, user_id=user_id, inputs=(source,), where="materials.bad_case")


def _bad_case(user_id: str, pages: list[dict], source_hash: str, *, raw: Any,
              source: str, model: str, reason: str, kind: str) -> str:
    # The shared writer caps input_json at 8000 characters. Keep a valid JSON
    # reference plus labelled excerpts, rather than letting it cut a full PDF.
    input_payload = {
        "source_hash": source_hash, "page_count": len(pages),
        "page_numbers": [page["page"] for page in pages],
        "source_excerpts": [{"page": page["page"], "text_excerpt": page["text"][:500]} for page in pages[:4]],
    }
    while len(json.dumps(input_payload, ensure_ascii=False)) > 7500:
        for page in input_payload["source_excerpts"]:
            page["text_excerpt"] = page["text_excerpt"][:len(page["text_excerpt"]) // 2]
    return write_bad_case(
        user_id=user_id, capability=CAPABILITY,
        input_payload=input_payload,
        actual_output=_safe_actual_output(raw, user_id=user_id, source=source),
        expected_output="3 条摘要、知识点、术语；每条页码和连续原句均可在课件中核对。",
        model=model, prompt_version=f"{PROMPT_NAME}@{PROMPT_VERSION}",
        problem_type="编造出处" if kind == "citation" else "安全拦截" if kind.startswith("guard") else "服务不可用" if kind == "provider" else "格式错",
        severity="高" if kind == "citation" or kind.startswith("guard") else "中",
        source="backend", fix_note=reason,
    )


def _attempt_timeout(remaining: float) -> float:
    # core's per-chain deadline is timeout * LLM_DEADLINE_FACTOR.
    try:
        factor = float(os.getenv("LLM_DEADLINE_FACTOR", "2.0"))
        if not math.isfinite(factor):
            factor = 2.0
    except ValueError:
        factor = 2.0
    return min(50.0, remaining / max(1.0, factor))


def generate_notes(user_id: str, pages: list[dict], *, title: str = "") -> dict[str, Any]:
    """Generate once plus one repair, returning only checked canonical content.

    Routing materials.summary to STRONG avoids the gateway's separate FAST
    empty-output escalation window. The caller retains all source data on error.
    """
    canonical, source_hash = _prepare_pages(pages)
    catalogue, evidence = build_evidence(canonical)
    if not evidence:
        raise MaterialError("notes_source_insufficient", "课件文字过少，暂时无法可靠整理，正文已保留", 422)
    source = data_block("source", json.dumps({"title": title[:160], "pages": catalogue}, ensure_ascii=False))
    if not has_llm(task=PROMPT_NAME):
        _bad_case(user_id, canonical, source_hash, raw={"error": "model_not_configured"},
                  source=source, model="unconfigured", reason="未配置学习文档使用的模型。", kind="provider")
        raise MaterialError("model_not_configured", "AI 模型还没配置，课件正文已保留，配置后可以重试整理", 503)
    system = _system_prompt()
    started = _clock()
    last: Any = None
    model = "unknown"
    reason, kind = "输出未通过校验", "schema"
    for attempt in range(2):
        remaining = GENERATION_BUDGET_SECONDS - (_clock() - started)
        if remaining < 1:
            reason, kind = "整理耗时超过本次预算，正文已保留。", "provider"
            break
        t0 = time.perf_counter()
        call: dict[str, Any] = {}
        parent = trace_context.current()
        context_manager = nullcontext(parent) if parent is not None else trace_context.step_context(operation=PROMPT_NAME)
        raw: Any = None
        output = None
        provider_failed = False
        guard_failed = False
        with context_manager as context:
            first_call = len(context["llm_calls"])
            try:
                raw = chat_json(system, source, task=PROMPT_NAME,
                                fallback={"_materials_unavailable": True},
                                timeout=_attempt_timeout(remaining), max_tokens=MAX_OUTPUT_TOKENS)
                calls = context["llm_calls"][first_call:]
                call = calls[-1] if calls else {}
                if _provider_unavailable(raw, call):
                    provider_failed = True
                    reason, kind = "模型服务本次不可用，未保存占位笔记。", "provider"
                elif _clock() - started > GENERATION_BUDGET_SECONDS:
                    provider_failed = True
                    reason, kind = "整理耗时超过本次预算，未保存迟到结果。", "provider"
                else:
                    output = validate_note_output(resolve_evidence_output(raw, evidence), canonical)
                    output["title"] = output["title"] or title.strip()[:160] or "本讲学习笔记"
                    rendered = json.dumps(output, ensure_ascii=False)
                    previous_guards = len(context["guardrails"])
                    checked = guard_text(rendered, user_id=user_id, inputs=(source,), where=PROMPT_NAME)
                    if checked != rendered:
                        output = None
                        guard_failed = True
                        unavailable = any(hit.get("type") == "guard_error" for hit in context["guardrails"][previous_guards:])
                        reason, kind = ("安全检查暂时不可用，未保存笔记。", "guard_unavailable") if unavailable else ("生成内容未通过安全检查，未保存笔记。", "guard")
            except _OutputIssue as issue:
                reason, kind = issue.reason, issue.kind
            except Exception:
                calls = context["llm_calls"][first_call:]
                call = calls[-1] if calls else {}
                provider_failed = True
                # Provider exception strings may contain URLs or credentials.
                raw = {"error": "provider_unavailable"}
                reason, kind = "模型服务本次不可用，未保存占位笔记。", "provider"
        model = _record_call(user_id, raw=raw, call=call, system=system, source=source,
                             latency_ms=int((time.perf_counter() - t0) * 1000), ok=output is not None)
        if output is not None:
            output["generation"] = {
                "model": model, "prompt_name": PROMPT_NAME, "prompt_version": PROMPT_VERSION,
                "source_hash": source_hash, "attempts": attempt + 1,
                "mode": str(call.get("mode") or (raw.get("_mode") if isinstance(raw, dict) else "") or "live"),
            }
            return output
        last = raw
        if provider_failed or guard_failed:
            break
        system += f"\n上次输出未通过检查：{reason}。请依据同一份正文重新生成完整 JSON，不添加任何字段或编造出处。"
    _bad_case(user_id, canonical, source_hash, raw=last, source=source, model=model,
              reason=reason, kind=kind)
    if kind == "provider":
        raise MaterialError("model_unavailable", "AI 整理暂时没有完成，课件正文已保留，可以稍后重试", 502)
    if kind == "guard":
        raise MaterialError("notes_output_blocked", "AI 整理结果未通过安全检查，课件正文已保留", 502)
    if kind == "guard_unavailable":
        raise MaterialError("E_GUARD_UNAVAILABLE", "安全检查暂时不可用，课件正文已保留，可以稍后重试", 503)
    raise MaterialError("notes_validation_failed", "AI 整理的格式或出处未通过检查，课件正文已保留，可以重试", 502)
