"""AI 能力“小满开场与建议”：每天第一次打开时小满先开口。

照地基范例接：版本化提示词 ``app/prompts/plan.opening/v1.md`` → 底座网关 ``chat_json`` →
校验 JSON 和语气 → 不合格把原因补进提示词重试一次 → 仍不合格用规则开场白，并写 bad case。
每次调用往 llm_calls 记一行（带 user_id、能力名、提示词版本、token）。
没配模型 key 时网关走离线占位，这里直接用规则开场白（source = rule）。

建议卡做什么由后端规则决定（returning / daily），这里只写开场白，不替用户做决定。
同一天只生成一次，存进 events（name=plan_opening），刷新页面不重复调用模型。
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from app.data_access.session import SessionLocal
from app.gateway.llm_gateway import chat_json, has_llm
from app.prompts import load_prompt
from app.study.common.bad_cases import write_bad_case
from app.study.common.models import Attempt, Goal, LlmCall, PlanDay, PlanTask, Question, StudyEvent, _now
from app.study.plan import returning, scheduler, service
from app.tools.prompt_data import UNTRUSTED_DATA_RULE

PROMPT_NAME = "plan.opening"
PROMPT_VERSION = "v1"
CAPABILITY = "开场与建议"
EVENT_NAME = "plan_opening"
MAX_CHARS = 60


class OpeningOutput(BaseModel):
    greeting: str = Field(min_length=1, max_length=MAX_CHARS)


# ---------- 事实：只给模型它需要的，不给“隔了几天” ----------


def gather_facts(session, user_id: str, today: date) -> dict[str, Any]:
    day = today.isoformat()
    goal = session.scalar(select(Goal).where(Goal.user_id == user_id))
    prev = session.scalars(
        select(PlanDay).where(PlanDay.user_id == user_id, PlanDay.day < day).order_by(PlanDay.day.desc()).limit(1)
    ).first()
    plan = session.scalar(select(PlanDay).where(PlanDay.user_id == user_id, PlanDay.day == day))
    tasks = (
        session.scalars(
            select(PlanTask).where(PlanTask.user_id == user_id, PlanTask.plan_day_id == plan.id).order_by(PlanTask.sort_order)
        ).all()
        if plan
        else []
    )
    first = next((t for t in tasks if t.status == "todo"), None)
    first_title = ""
    if first is not None:
        first_title = service._task_view(first, plan.intensity if plan else "normal")["title"]

    # 上一次打开那天做错、到现在还没做对的题（按讲数一下）。
    last_mistakes: dict[str, int] = {}
    yesterday = False
    if prev is not None:
        prev_day = date.fromisoformat(prev.day)
        yesterday = (today - prev_day).days == 1
        questions = {
            row.id: row.lecture_id
            for row in session.scalars(select(Question).where(Question.user_id == user_id)).all()
        }
        latest: dict[str, Attempt] = {}
        for attempt in session.scalars(
            select(Attempt).where(Attempt.user_id == user_id).order_by(Attempt.created_at, Attempt.id)
        ).all():
            latest[attempt.question_id] = attempt
        for question_id, attempt in latest.items():
            when = service._local_date(attempt.created_at)
            if not attempt.correct and when is not None and when < today and when >= prev_day:
                lecture = questions.get(question_id, "")
                last_mistakes[lecture] = last_mistakes.get(lecture, 0) + 1
    lecture_id, count = max(last_mistakes.items(), key=lambda kv: kv[1]) if last_mistakes else ("", 0)
    card = service._pending_card(session, user_id, day)
    return {
        "needs_setup": service.needs_setup(goal),
        "paused": bool(goal is not None and goal.status == "paused"),
        "first_visit": prev is None,
        "last_was_yesterday": yesterday,
        "last_mistakes": {"lecture_no": scheduler.lecture_no_for(lecture_id), "count": count} if count else None,
        "first_task": first_title,
        "task_count": len(tasks),
        "has_card": card is not None,
        "card_title": service._card_meta(card).get("title") if card is not None else "",
    }


# ---------- 规则开场白（没 key、或 AI 输出不合格时用）----------


def rule_greeting(facts: dict[str, Any]) -> str:
    if facts.get("needs_setup"):
        return "你好，我是小满。先说说你想学成什么样，我帮你拆成每天三件。"
    if facts.get("paused"):
        return "想学的时候随时回来，目标我先替你收着。"
    if facts.get("has_card"):
        return "欢迎回来。今天还是三件，先看看这样安排行不行。"
    mistakes = facts.get("last_mistakes")
    if mistakes and mistakes.get("lecture_no"):
        when = "昨天" if facts.get("last_was_yesterday") else "上次"
        return f"早。{when}第 {mistakes['lecture_no']} 讲有 {mistakes['count']} 道没做对，今天先花几分钟重做。"
    if facts.get("first_visit"):
        return "你好，我是小满。今天的三件在左边，先做第一件就好。"
    if facts.get("first_task"):
        return f"早。今天的三件排好了，先做「{facts['first_task']}」。"
    return "早。今天的三件都做完了，想学的话可以再练几道。"


def _tone_ok(text: str) -> Optional[str]:
    """语气检查：不合格返回原因。"""
    for word in returning.BANNED_WORDS + ("几天没", "好几天", "终于"):
        if word in text:
            return f"出现了不该说的词“{word}”"
    return None


def _parse(raw: Any) -> tuple[Optional[str], str]:
    if not isinstance(raw, dict):
        return None, "输出不是 JSON 对象"
    data = {key: value for key, value in raw.items() if not str(key).startswith("_")}
    try:
        out = OpeningOutput.model_validate(data)
    except ValidationError:
        return None, f"字段只能是 greeting，且不超过 {MAX_CHARS} 个字"
    reason = _tone_ok(out.greeting)
    if reason:
        return None, reason
    return out.greeting.strip(), ""


def _record(user_id: str, *, model: str, prompt_tokens: int, completion_tokens: int, latency_ms: int, ok: bool) -> None:
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


def generate(user_id: str, facts: dict[str, Any]) -> dict[str, Any]:
    fallback = rule_greeting(facts)
    offline = not has_llm(task=PROMPT_NAME)
    system = load_prompt(PROMPT_NAME, PROMPT_VERSION, untrusted_data_rule=UNTRUSTED_DATA_RULE)
    user = "<source>\n" + json.dumps(facts, ensure_ascii=False) + "\n</source>"
    last: Any = None
    reason = ""
    for attempt in range(2):
        t0 = time.perf_counter()
        raw = chat_json(system, user, fallback={"greeting": fallback}, task=PROMPT_NAME, timeout=20, max_tokens=200)
        model = str(raw.get("_model") or ("mock" if offline else "")) if isinstance(raw, dict) else ""
        greeting, reason = _parse(raw)
        rendered = json.dumps(raw, ensure_ascii=False) if isinstance(raw, dict) else str(raw)
        _record(
            user_id,
            model=model,
            prompt_tokens=len(system) + len(user),
            completion_tokens=max(1, len(rendered)),
            latency_ms=int((time.perf_counter() - t0) * 1000),
            ok=greeting is not None,
        )
        if greeting is not None:
            live = not offline and isinstance(raw, dict) and raw.get("_mode") != "mock"
            return {"greeting": greeting, "source": "ai" if live else "rule", "attempts": attempt + 1}
        last = raw
        system += f"\n上次输出没通过检查：{reason}。请重新输出完整 JSON，只有 greeting 一个字段。"
    bad_id = write_bad_case(
        user_id=user_id,
        capability=CAPABILITY,
        input_payload=facts,
        actual_output=json.dumps(last, ensure_ascii=False) if isinstance(last, dict) else str(last),
        expected_output=json.dumps({"greeting": fallback}, ensure_ascii=False),
        model="unknown",
        prompt_version=f"{PROMPT_NAME}@{PROMPT_VERSION}",
        problem_type="语气不对" if "不该说" in reason else "格式错",
        severity="中",
        source="backend",
        fix_note=f"两次都没过检查：{reason}。已改用规则开场白。",
    )
    return {"greeting": fallback, "source": "rule", "attempts": 2, "bad_case_id": bad_id}


def opening(user_id: str) -> dict[str, Any]:
    """今天的开场白。同一天只生成一次。"""
    service.ensure_today_plan(user_id)
    today = service.today_for(user_id)
    day = today.isoformat()
    with SessionLocal() as session:
        cached = session.scalars(
            select(StudyEvent)
            .where(StudyEvent.user_id == user_id, StudyEvent.name == EVENT_NAME)
            .order_by(StudyEvent.at.desc())
        ).all()
        for row in cached:
            props = service._loads(row.props_json, {})
            if props.get("day") == day:
                return {**props, "cached": True}
        facts = gather_facts(session, user_id, today)
    result = generate(user_id, facts)
    data = {
        "day": day,
        "greeting": result["greeting"],
        "source": result["source"],
        "mood": "wave",
        "label": "AI 整理，可以改" if result["source"] == "ai" else "模拟",
    }
    with SessionLocal() as session:
        session.add(
            StudyEvent(
                id=uuid.uuid4().hex,
                user_id=user_id,
                name=EVENT_NAME,
                at=_now(),
                props_json=json.dumps(data, ensure_ascii=False),
            )
        )
        session.commit()
    return {**data, "cached": False}

