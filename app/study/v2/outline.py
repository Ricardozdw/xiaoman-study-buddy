"""版本化学习大纲能力与不依赖数据库的阶段划分。"""
from __future__ import annotations

import json
import math
import re
import time
import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.data_access.session import SessionLocal
from app.gateway.llm_gateway import chat_json, has_llm
from app.prompts import load_prompt
from app.study.common.bad_cases import write_bad_case
from app.study.common.db import ensure_schema
from app.study.common.models import LlmCall
from app.tools.prompt_data import UNTRUSTED_DATA_RULE

PROMPT_NAME = "goal.outline"
PROMPT_VERSION = "v1"
# 只拦可观察的、被任务卡明确禁止的事实形式，不把关键知识中的数字当成日期。
UNVERIFIED = re.compile(r"\d{4}[-年/]\d{1,2}|\d{1,2}月\d{1,2}[日号]|\d+(?:\.\d+)?\s*(?:元|美元|人民币|分值|分(?!钟))|[¥￥$]\s*\d|第\s*[\d一二三四五六七八九十]+\s*页|官方考纲第")


class Unit(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    points: list[str] = Field(min_length=1, max_length=20)

    @field_validator("points")
    @classmethod
    def clean_points(cls, points):
        points = [point.strip() for point in points]
        if any(not point or len(point) > 1000 for point in points):
            raise ValueError("要点不能为空或超过 1000 字")
        return points


def validate_units(raw, *, generated=False):
    if not isinstance(raw, list) or not (4 <= len(raw) <= 12 if generated else 1 <= len(raw) <= 20):
        raise ValueError("单元数量不符合范围")
    units = [Unit.model_validate(item).model_dump() for item in raw]
    if len({item["title"] for item in units}) != len(units):
        raise ValueError("单元标题不能重复")
    if generated and (any(not 3 <= len(item["points"]) <= 6 for item in units)
                      or UNVERIFIED.search(json.dumps(units, ensure_ascii=False))):
        raise ValueError("大纲要点数量或事实形式不符合要求")
    return [{"no": index, **item} for index, item in enumerate(units, 1)]


def split_stages(unit_count: int) -> list[dict]:
    """<=4 一阶段；否则 ceil(N/4) 阶段，均分、余数放前。不读写外部状态。"""
    if isinstance(unit_count, bool) or not isinstance(unit_count, int) or not 1 <= unit_count <= 20:
        raise ValueError("单元数须为 1–20 的整数")
    count = math.ceil(unit_count / 4)
    size, extra = divmod(unit_count, count)
    stages, start = [], 1
    for index in range(count):
        stop = start + size + (index < extra)
        stages.append({"no": index + 1, "title": f"第 {index + 1} 阶段", "unit_nos": list(range(start, stop)), "started_at": ""})
        start = stop
    return stages


def mock_units(goal):
    deadline = goal.get("deadline")
    days = max(1, (date.fromisoformat(deadline) - date.fromisoformat(goal["today"])).days) if deadline else 30
    count = max(4, min(12, math.ceil(days * int(goal.get("daily_minutes", 30)) / 180)))
    kind = goal.get("goal_type", "exam")
    first, middle, practice, last = {
        "exam": ("考试概览与准备", "核心概念", "综合练习", "考前复盘"),
        "course": ("课程结构与准备", "章节主题", "综合应用", "学习复盘"),
        "skill": ("技能入门与准备", "基本技能", "场景练习", "综合实践与复盘"),
    }[kind]
    titles = [first] + [f"{middle} {index}" for index in range(1, count - 2)] + [practice, last]
    return [{"title": title, "points": ["理解本单元的基本概念与适用范围", "结合常见例子梳理关键方法", "通过练习检查理解并记录疑问"]} for title in titles]


def generate_outline(user_id, goal):
    ensure_schema()
    from app.study.plan.service import today_for
    goal = {**goal, "today": goal.get("today") or today_for(user_id).isoformat()}
    fallback = mock_units(goal)
    system = load_prompt(PROMPT_NAME, PROMPT_VERSION, untrusted_data_rule=UNTRUSTED_DATA_RULE)
    user = "<source>\n" + json.dumps(goal, ensure_ascii=False) + "\n</source>"
    offline = not has_llm(task=PROMPT_NAME)
    last, reason = None, ""
    for attempt in range(2):
        started = time.perf_counter()
        try:
            last = chat_json(system, user, fallback={"units": fallback}, task=PROMPT_NAME, timeout=30, max_tokens=2500)
            units = validate_units(last.get("units"), generated=True)
            valid = True
        except Exception as exc:
            # 不把异常里的用户输入、模型原文或凭据回显给用户。
            reason, valid = type(exc).__name__, False
        with SessionLocal() as session:
            session.add(LlmCall(id=uuid.uuid4().hex, user_id=user_id, capability=PROMPT_NAME,
                                prompt_name=PROMPT_NAME, prompt_version=PROMPT_VERSION,
                                model=str(last.get("_model", "mock" if offline else "unknown"))[:128] if isinstance(last, dict) else "unknown",
                                prompt_tokens=len(system) + len(user), completion_tokens=len(json.dumps(last, ensure_ascii=False)),
                                latency_ms=int((time.perf_counter() - started) * 1000), ok=int(valid), estimated=1))
            session.commit()
        if valid:
            return units, offline or last.get("_mode") == "mock"
        system += "\n上次输出未通过结构或事实形式检查，请按要求重新输出完整 JSON。"
    write_bad_case(user_id=user_id, capability=PROMPT_NAME, input_payload=goal,
                   actual_output=json.dumps(last, ensure_ascii=False), expected_output="4–12 个单元，每单元 3–6 要点，无未经核实的事实",
                   prompt_version=f"{PROMPT_NAME}@{PROMPT_VERSION}", problem_type="格式错", fix_note=f"两次检查失败（{reason}），已使用模拟大纲")
    return validate_units(fallback, generated=True), True
