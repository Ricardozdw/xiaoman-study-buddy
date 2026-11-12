"""版本化通用讲解能力：按大纲单元生成一讲讲解，供「学第 N 讲」使用。"""
from __future__ import annotations

import json
import time
import uuid

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.data_access.session import SessionLocal
from app.gateway.llm_gateway import chat_json, has_llm
from app.prompts import load_prompt
from app.study.common.bad_cases import write_bad_case
from app.study.common.db import ensure_schema
from app.study.common.models import LlmCall, MaterialPage
from app.study.v2.models import GoalOutline, UnitLecture
from app.tools.prompt_data import UNTRUSTED_DATA_RULE

PROMPT_NAME = "unit.lecture"
PROMPT_VERSION = "v1"
LABEL = "通用知识，没有出处"


def current_outline_id(user_id: str) -> str:
    """当前目标已确认的 V2 大纲 id（无则返回空串）。"""
    from app.study.common.models import Goal
    with SessionLocal() as session:
        goal = session.scalar(select(Goal).where(Goal.user_id == user_id))
        if goal is None:
            return ""
        return json.loads(goal.summary_json or "{}").get("v2", {}).get("outline_id", "")


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    heading: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=2000)
    example: str = Field(default="", max_length=2000)


class Lecture(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    sections: list[Section] = Field(min_length=1, max_length=8)


def _load_outline_and_unit(user_id: str, outline_id: str, unit_no: int):
    with SessionLocal() as session:
        outline = session.get(GoalOutline, outline_id)
        if outline is None or outline.user_id != user_id:
            return None, None
        units = json.loads(outline.units_json)
        unit = next((u for u in units if u.get("no") == unit_no), None)
        return outline, unit


PLACEHOLDER = "（讲解暂未生成，可稍后再点本讲）"


def _cached(user_id: str, outline_id: str, unit_no: int):
    """读缓存的讲解。只认真生成过的；以前误存的占位讲解跳过，下次重新生成。"""
    with SessionLocal() as session:
        rows = session.scalars(select(UnitLecture).where(
            UnitLecture.user_id == user_id,
            UnitLecture.outline_id == outline_id,
            UnitLecture.unit_no == unit_no)).all()
        for row in rows:
            if PLACEHOLDER in row.sections_json:
                continue
            return {"title": row.title, "sections": json.loads(row.sections_json), "label": row.label}
        return None


def material_text(title: str, sections: list[dict]) -> str:
    """把一讲讲解排成一页正文，作为没交资料时问答和出题的依据。"""
    parts = [title.strip()]
    for section in sections:
        parts.append(section["heading"].strip())
        parts.append(section["content"].strip())
        if (section.get("example") or "").strip():
            parts.append("例：" + section["example"].strip())
    return "\n".join(part for part in parts if part)


def _sync_material(user_id: str, outline_id: str, unit_no: int, title: str, sections: list[dict]) -> None:
    """没交资料时，这一讲的“通用知识资料”原本只有标题和几行要点；讲解生成后换成讲解正文。

    只改确认大纲时系统自己写的那一页（id 固定），用户上传的资料不动。
    """
    with SessionLocal() as session:
        page = session.get(MaterialPage, f"v2-outline-{outline_id}-page-{unit_no}")
        if page is None or page.user_id != user_id:
            return
        text = material_text(title, sections)
        if page.text != text:
            page.text = text
            session.commit()


def _is_fallback(out) -> bool:
    """模型网关在失败时会把 fallback 原样返回并打标；这类结果不能当成讲解。"""
    return not isinstance(out, dict) or out.get("_mode") in ("mock", "mock_fallback") or bool(out.get("_parse")) or bool(out.get("_model_error"))


def generate(user_id: str, outline_id: str, unit_no: int, goal: dict):
    """生成或读取某一讲的讲解。返回 (lecture_dict, mock)。"""
    ensure_schema()
    outline, unit = _load_outline_and_unit(user_id, outline_id, unit_no)
    if unit is None:
        raise ValueError("单元不存在")
    hit = _cached(user_id, outline_id, unit_no)
    if hit is not None:
        # 以前学过的讲次：补上这一页，之后的练习和问答也基于讲解。
        _sync_material(user_id, outline_id, unit_no, hit["title"], hit["sections"])
        return hit, False

    system = load_prompt(PROMPT_NAME, PROMPT_VERSION, untrusted_data_rule=UNTRUSTED_DATA_RULE)
    payload = {
        "goal_type": goal.get("goal_type") or outline.goal_type,
        "goal_title": goal.get("title") or outline.title,
        "unit_title": unit["title"],
        "points": unit.get("points", []),
    }
    user_msg = "<source>\n" + json.dumps(payload, ensure_ascii=False) + "\n</source>"
    offline = not has_llm(task=PROMPT_NAME)
    fallback = {"title": unit["title"], "sections": [
        {"heading": unit["title"], "content": PLACEHOLDER, "example": ""}]}
    last: dict = {}
    lecture: dict = {}
    valid = False
    for attempt in range(2):
        started = time.perf_counter()
        try:
            last = chat_json(system, user_msg, fallback=fallback, task=PROMPT_NAME, timeout=60, max_tokens=4000)
            if _is_fallback(last):
                raise ValueError("fallback")
            data = {k: v for k, v in last.items() if not k.startswith("_")}
            lecture = Lecture.model_validate(data).model_dump()
            valid = True
        except Exception:
            valid = False
        with SessionLocal() as session:
            session.add(LlmCall(
                id=uuid.uuid4().hex, user_id=user_id, capability="通用讲解", prompt_name=PROMPT_NAME,
                prompt_version=PROMPT_VERSION,
                model=str(last.get("_model", "mock" if offline else "unknown"))[:128] if isinstance(last, dict) else "unknown",
                prompt_tokens=len(system) + len(user_msg),
                completion_tokens=len(json.dumps(last, ensure_ascii=False)),
                latency_ms=int((time.perf_counter() - started) * 1000), ok=int(valid), estimated=1))
            session.commit()
        if valid:
            break
        system += "\n上次输出未通过结构检查，请按要求重新输出完整 JSON。"

    if not valid:
        write_bad_case(user_id=user_id, capability=PROMPT_NAME, input_payload=payload,
                       actual_output=json.dumps(last, ensure_ascii=False),
                       expected_output="title + 3–5 个 section（heading/content/example）",
                       prompt_version=f"{PROMPT_NAME}@{PROMPT_VERSION}", problem_type="格式错",
                       fix_note="两次结构检查失败，已使用占位讲解")
        lecture = fallback
        # 占位讲解不进缓存，用户再点一次就会重新生成。
        return {"title": lecture["title"], "sections": lecture["sections"], "label": LABEL}, True

    with SessionLocal() as session:
        session.add(UnitLecture(id=uuid.uuid4().hex, user_id=user_id, outline_id=outline_id, unit_no=unit_no,
                                title=lecture["title"],
                                sections_json=json.dumps(lecture["sections"], ensure_ascii=False)))
        session.commit()
    _sync_material(user_id, outline_id, unit_no, lecture["title"], lecture["sections"])

    return {"title": lecture["title"], "sections": lecture["sections"], "label": LABEL}, offline or last.get("_mode") == "mock"
