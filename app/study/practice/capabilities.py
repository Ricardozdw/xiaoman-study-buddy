"""版本化出题/换问法 + 盲答自检；只经底座网关调用模型。"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid

from app.agent.harness.context import step_context
from app.agent.harness.guardrails import guard_text
from app.data_access.session import SessionLocal
from app.gateway.llm_gateway import ModelTier, chat_json, has_llm
from app.prompts import load_prompt
from app.study.common.bad_cases import write_bad_case
from app.study.common.models import LlmCall
from app.study.practice.schemas import CheckedQuiz, GeneratedQuestion, GeneratedQuiz, Option
from app.tools.prompt_data import UNTRUSTED_DATA_RULE

VERSION = "v1"
PROMPT_VERSIONS = {"practice.generate": "v3", "practice.check": "v1", "practice.rephrase": "v3"}


class PracticeError(ValueError):
    pass


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _call(user_id: str, name: str, payload: dict, output_type, *, fast=False):
    version = PROMPT_VERSIONS[name]
    system = load_prompt(name, version, untrusted_data_rule=UNTRUSTED_DATA_RULE)
    user = "<source>\n" + json.dumps(payload, ensure_ascii=False) + "\n</source>"
    for attempt in range(2):
        started = time.perf_counter()
        raw = None
        valid = False
        with step_context(user_id=user_id, capability=name) as context:
            try:
                raw = chat_json(system, user, tier=ModelTier.FAST if fast else ModelTier.STRONG,
                                # 出题走强档：评测里 p90 约 11.4s，12s 上限在真实使用中常超时；改 30s（与大纲生成一致）。
                                timeout=12 if fast else 30, max_tokens=4500 if not fast else 600)
                if raw.get("error") or raw.get("_parse") or raw.get("_mode") in ("mock", "mock_fallback"):
                    raise PracticeError("模型暂时不可用，请稍后重试")
                data = {k: v for k, v in raw.items() if not k.startswith("_")}
                parsed = output_type.model_validate(data)
                rendered = json.dumps(parsed.model_dump(), ensure_ascii=False)
                if guard_text(rendered, user_id=user_id, inputs=(user,), where=name) != rendered:
                    raise PracticeError("题目未通过安全检查，请重试")
                valid = True
                return parsed
            except Exception as exc:
                if attempt == 1 or isinstance(exc, PracticeError):
                    write_bad_case(user_id=user_id, capability=name,
                                   input_payload={"lecture_id": payload.get("lecture_id"), "count": payload.get("count")},
                                   actual_output="模型未通过输出校验", problem_type="格式错", severity="中",
                                   prompt_version=f"{name}@{version}")
                    raise PracticeError("题目未通过校验，请重试") from None
                # 不把可能含有资料或隐私的 ValidationError 原文放回提示词或日志。
                system += "\n上次输出未通过检查。请严格按规定重写完整 JSON。"
            finally:
                calls = context["llm_calls"]
                call = calls[-1] if calls else {}
                usage = call.get("usage") or {}
                estimated = not bool(call.get("usage"))
                with SessionLocal() as session:
                    session.add(LlmCall(
                        id=uuid.uuid4().hex, user_id=user_id, capability=name,
                        prompt_name=name, prompt_version=version,
                        model=str(call.get("model") or (raw or {}).get("_model") or "unknown")[:128],
                        prompt_tokens=int(usage.get("prompt_tokens", call.get("tokens_in_est", len(system) + len(user)))),
                        completion_tokens=int(usage.get("completion_tokens", call.get("tokens_out_est", 0))),
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        estimated=int(estimated), ok=int(valid),
                    ))
                    session.commit()


def mock_questions(pages: list[dict], count: int, difficulty: str, original: dict | None) -> list[GeneratedQuestion]:
    """离线交互样例，不声称是模型出题，不用于质量或速度验收。"""
    result = []
    for i in range(count):
        page = pages[i % len(pages)]
        quote = page["text"].strip()[:200]
        point = original["knowledge_point"] if original else f"原文第 {page['page']} 页"
        prefix = "换个问法，" if original else ""
        result.append(GeneratedQuestion(
            stem=f"（模拟 {i+1}）{prefix}以下哪句与第 {page['page']} 页原文一致？",
            options=[{"id": "A", "text": "资料没有说明任何内容"}, {"id": "B", "text": quote},
                     {"id": "C", "text": "可以忽略原文，随意推断"}],
            answer="B", analysis=f"原文写道：{quote}", source={"page": page["page"], "quote": quote},
            difficulty=difficulty, knowledge_point=point,
        ))
    return result


def balance_answer(q: GeneratedQuestion) -> GeneratedQuestion:
    """模型出的单选题正确答案大多在 A（实测约八成），用户只选 A 就能拿高分。
    这里用题干的哈希决定正确答案落在哪一位（同一道题永远一样，整体在 A–D 上均匀），
    其余选项保持原来的相对顺序，再按位置重新编号。解析里不引用选项字母，不受影响。"""
    texts = [o.text for o in q.options]
    letters = [o.id for o in q.options]
    if q.answer not in letters or len(texts) < 2:
        return q
    right = texts[letters.index(q.answer)]
    others = [t for i, t in enumerate(texts) if letters[i] != q.answer]
    target = int(hashlib.sha256(compact(q.stem).encode("utf-8")).hexdigest(), 16) % len(texts)
    order = others[:target] + [right] + others[target:]
    ids = ["A", "B", "C", "D"][:len(order)]
    return q.model_copy(update={"options": [Option(id=i, text=t) for i, t in zip(ids, order)], "answer": ids[target]})


def generate(user_id: str, lecture_id: str, pages: list[dict], count: int, difficulty: str,
             original: dict | None = None, exclude_stems: list[str] | None = None) -> tuple[list[GeneratedQuestion], bool]:
    if not pages or not any(p["text"].strip() for p in pages):
        raise PracticeError("这一讲还没有可用正文，请先交资料")
    pages = [p for p in pages if p["text"].strip()]
    if sum(len(p["text"]) for p in pages) > 100000:
        raise PracticeError("这一讲太长，请先拆成较小的讲次")
    if not has_llm(ModelTier.STRONG):
        return mock_questions(pages, count, difficulty, original), True
    # 单次模型输出仍限制 5 题，最多分 3 批生成，避免 15 题被输出长度截断。
    if count > 5:
        combined = []
        for offset in range(0, count, 5):
            batch, _ = generate(user_id, lecture_id, pages, min(5, count - offset), difficulty,
                                original, [q.stem for q in combined])
            combined.extend(batch)
        return combined, False
    payload = {"lecture_id": lecture_id, "count": count, "difficulty": difficulty,
               "pages": [{"page": p["page"], "text": p["text"]} for p in pages],
               "exclude_stems": exclude_stems or []}
    if original:
        payload["original"] = original
    else:
        # 没交资料时，这一讲的“资料”是小满写的通用知识（确认大纲时系统写入的那一页）；告诉模型别把它说成用户的资料。
        general = all(str(p.get("file_id", "")).startswith("v2-outline-") for p in pages)
        payload["source_kind"] = "通用知识" if general else "用户资料"
    name = "practice.rephrase" if original else "practice.generate"
    generated = _call(user_id, name, payload, GeneratedQuiz)
    page_map = {p["page"]: compact(p["text"]) for p in pages}
    candidates = []
    seen = {compact(stem) for stem in (exclude_stems or [])}
    for q in generated.questions[:count]:
        valid = (compact(q.source.quote) in page_map.get(q.source.page, "")
                 and q.difficulty == difficulty and compact(q.stem) not in seen)
        if original:
            valid = valid and compact(q.stem) not in {compact(original["stem"]), compact(original.get("previous_stem", ""))}
            valid = valid and q.knowledge_point == original["knowledge_point"]
        if valid:
            candidates.append(q)
            seen.add(compact(q.stem))
        else:
            write_bad_case(user_id=user_id, capability=name, input_payload={"lecture_id": lecture_id},
                           actual_output=json.dumps(q.model_dump(), ensure_ascii=False),
                           expected_output="逐字出处、指定难度、原知识点和不重复的题干；不合格题已丢弃",
                           problem_type="题目有误", severity="高", prompt_version=f"{name}@{PROMPT_VERSIONS[name]}")
    if not candidates:
        raise PracticeError("没有通过出处检查的题目，请重试")
    # 一组题一次盲答，不传标准答案、解析或知识点提示。
    blind = {"lecture_id": lecture_id, "pages": payload["pages"], "questions": [
        {"index": i, "stem": q.stem, "options": [o.model_dump() for o in q.options]}
        for i, q in enumerate(candidates)
    ]}
    checked = _call(user_id, "practice.check", blind, CheckedQuiz, fast=True)
    accepted = []
    for i, q in enumerate(candidates):
        answers = [a.answer for a in checked.answers if a.index == i]
        if answers == [q.answer]:
            accepted.append(q)
        else:
            write_bad_case(user_id=user_id, capability=name, input_payload={"lecture_id": lecture_id, "index": i},
                           actual_output="出题答案与独立盲答不一致，已丢弃", problem_type="题目有误",
                           severity="高", prompt_version=f"{name}@{PROMPT_VERSIONS[name]}")
    if not accepted:
        raise PracticeError("题目自检没有通过，请重试")
    # 盲答自检通过后再打散正确答案的位置（自检看的是模型原样输出）。
    return [balance_answer(q) for q in accepted], False
