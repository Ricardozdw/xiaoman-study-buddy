"""目标拆解（PRD F1）。

第一次见面在对话里问：目标和日期、一共几讲、学到第几讲、每天多少时间。
每题都有快捷回复，也能自己输入；跳过或听不懂的项，按默认值排，并写明“先按……安排”，
不当成用户的选择（产品规则 6）。答完出一张目标拆解卡：分阶段、每天三件的来源、默认强度。
点“好”才生效，可撤销；“说说怎么改”用一句话重排，出一张新卡替换旧卡。
"""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import select

from app.data_access.session import SessionLocal
from app.study.common import store
from app.study.common.models import AgentAction, Goal, PlanDay
from app.study.plan import parse, returning, service

FIELDS = ("title", "exam_date", "lecture_count", "learned_up_to", "daily_minutes")
DEFAULTS: dict[str, Any] = {
    "title": "把这门课学完",
    "exam_date": None,
    "lecture_count": 12,
    "learned_up_to": 0,
    "daily_minutes": 30,
}
DEFAULT_TEXT = {
    "title": "目标先按“把这门课学完”安排",
    "exam_date": "先按不设考试日期安排",
    "lecture_count": "先按一共 12 讲安排",
    "learned_up_to": "先按从第 1 讲开始安排",
    "daily_minutes": "先按每天 30 分钟安排",
}
INTENSITY_TEXT = {"light": "轻松，约 15 分钟", "normal": "正常，约 30 分钟", "sprint": "冲刺，约 50 分钟"}
BADGE = "模拟"
KIND_GOAL_SETUP = "goal_setup"

QUESTIONS = [
    {"key": "title", "text": "想学成什么样？比如考过 PMP", "quick_replies": ["考过 PMP", "跟完这门网课"], "input": "text"},
    {"key": "exam_date", "text": "考试（或想学完）是哪天？", "quick_replies": ["一个月后", "两个月后", "还没定"], "input": "date"},
    {"key": "lecture_count", "text": "这门课一共几讲？", "quick_replies": ["8 讲", "12 讲", "20 讲"], "input": "number"},
    {"key": "learned_up_to", "text": "已经学到第几讲了？", "quick_replies": ["还没开始", "第 3 讲", "第 6 讲"], "input": "number"},
    {"key": "daily_minutes", "text": "每天大概有多少时间？", "quick_replies": ["15 分钟", "30 分钟", "50 分钟"], "input": "minutes"},
]


def questions() -> dict[str, Any]:
    for item in QUESTIONS:
        item.setdefault("skip_label", "跳过")
        item.setdefault("default_text", DEFAULT_TEXT[item["key"]])
    return {"questions": QUESTIONS, "note": "一次问一题；跳过的按默认排，会写明“先按……安排”。"}


# ---------- 解析回答 ----------


def normalize(answers: dict[str, Any], today: date) -> tuple[dict[str, Any], dict[str, bool], list[str]]:
    """回答 → (取值, 哪些是用户选的, 没听懂的项)。没答 / 听不懂的用默认值，chosen 为 False。"""
    values = dict(DEFAULTS)
    chosen = {key: False for key in FIELDS}
    unclear: list[str] = []
    for key in FIELDS:
        raw = answers.get(key)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            continue
        text = str(raw).strip()
        parsed: Any
        if key == "title":
            parsed = text[:200]
        elif key == "exam_date":
            parsed = parse.parse_date(text, today)
            if parsed == parse.NO_DATE:
                parsed = None
                values[key], chosen[key] = None, True  # 明确说还没定，是用户的选择
                continue
            if parsed is not None and date.fromisoformat(parsed) <= today:
                parsed = None
        elif key == "lecture_count":
            parsed = parse.parse_lecture_count(text)
        elif key == "learned_up_to":
            parsed = parse.parse_learned(text)
        else:
            parsed = parse.parse_minutes(text)
            if parsed is not None and not 5 <= parsed <= 600:
                parsed = None
        if parsed is None:
            unclear.append(key)
            continue
        values[key], chosen[key] = parsed, True
    if values["learned_up_to"] > values["lecture_count"]:
        values["learned_up_to"] = values["lecture_count"]
    intensity = answers.get("intensity")
    if intensity in returning_levels():
        values["intensity"], chosen["intensity"] = intensity, True
    return values, chosen, unclear


def returning_levels() -> tuple[str, ...]:
    return ("light", "normal", "sprint")


def intensity_for(minutes: int) -> str:
    if minutes <= 20:
        return "light"
    if minutes <= 40:
        return "normal"
    return "sprint"


# ---------- 拆解：分阶段 ----------


def _md(value: date) -> str:
    return f"{value.month} 月 {value.day} 日"


def breakdown(values: dict[str, Any], today: date) -> dict[str, Any]:
    """按规则拆成阶段（学新讲 / 刷题 / 冲刺），算复习底线和默认强度。"""
    count = int(values["lecture_count"])
    learned = int(values["learned_up_to"])
    remaining = max(count - learned, 0)
    exam = date.fromisoformat(values["exam_date"]) if values.get("exam_date") else None
    intensity = values.get("intensity") or intensity_for(int(values["daily_minutes"]))
    phases: list[dict[str, Any]] = []
    notes: list[str] = []
    review_floor = returning.REVIEW_FLOOR_DAYS
    learn_end = today + timedelta(days=remaining - 1) if remaining else None
    if remaining:
        span = f"第 {learned + 1}–{count} 讲" if remaining > 1 else f"第 {count} 讲"
        phases.append(
            {"name": "学新讲", "start": today.isoformat(), "end": learn_end.isoformat(), "note": f"每天一讲，{span}"}
        )
    if exam is None:
        phases.append({"name": "刷题", "start": None, "end": None, "note": "讲学完以后，一边刷题一边补错题"})
        notes.append("没有考试日期，就按每天一讲往前走")
    else:
        days_left = (exam - today).days
        spare = days_left - remaining
        review_floor = min(returning.REVIEW_FLOOR_DAYS, max(spare, 0))
        sprint_days = 3 if spare >= 6 else max(spare // 2, 0)
        practice_start = (learn_end + timedelta(days=1)) if learn_end else today
        practice_end = exam - timedelta(days=sprint_days + 1)
        if spare - sprint_days > 0:
            phases.append(
                {"name": "刷题", "start": practice_start.isoformat(), "end": practice_end.isoformat(), "note": "练一练和补一补为主"}
            )
        if sprint_days > 0:
            phases.append(
                {
                    "name": "冲刺",
                    "start": (exam - timedelta(days=sprint_days)).isoformat(),
                    "end": (exam - timedelta(days=1)).isoformat(),
                    "note": f"考前 {sprint_days} 天，整体过一遍",
                }
            )
        if spare < 0:
            notes.append(f"按一天一讲，考试前还差 {-spare} 讲学不完，可以说说怎么改，比如把考试日期往后挪")
    return {
        "phases": phases,
        "review_floor": review_floor,
        "default_intensity": intensity,
        "remaining": remaining,
        "notes": notes,
    }


def _phase_line(phase: dict[str, Any]) -> str:
    if phase.get("start") and phase.get("end"):
        start, end = date.fromisoformat(phase["start"]), date.fromisoformat(phase["end"])
        when = _md(start) if start == end else f"{_md(start)}–{_md(end)}"
        return f"{phase['name']}：{when}，{phase['note']}"
    return f"{phase['name']}：{phase['note']}"


def build_card(values: dict[str, Any], chosen: dict[str, bool], today: date) -> dict[str, Any]:
    plan = breakdown(values, today)
    exam = values.get("exam_date")
    head = f"目标：{values['title']}" + (f"（考试 {_md(date.fromisoformat(exam))}）" if exam else "")
    lines = [head]
    lines += [_phase_line(phase) for phase in plan["phases"]]
    lines.append("每天最多三件：学新的 / 练一练 / 补一补")
    lines.append(f"默认强度：{INTENSITY_TEXT[plan['default_intensity']]}，想多学加强度，不加件数")
    lines += plan["notes"]
    lines += [DEFAULT_TEXT[key] for key in FIELDS if not chosen.get(key)]
    return {
        "kind": KIND_GOAL_SETUP,
        "type": "goal",
        "title": "先把目标拆开",
        "lines": lines,
        "badge": BADGE,
        "collapsed_text": "目标已定好，今天的三件在左边",
        "decline_label": "先不用",
        "revise_label": "说说怎么改",
        "options": [{"id": "ok", "label": "好", "effect": {}}],
        "values": values,
        "chosen": chosen,
        "breakdown": plan,
    }


# ---------- 出卡 / 改 / 生效 / 撤销 ----------


def _expire_pending(session, user_id: str) -> None:
    rows = session.scalars(
        select(AgentAction).where(AgentAction.user_id == user_id, AgentAction.status == "pending")
    ).all()
    for row in rows:
        if service._card_meta(row).get("plan_line"):
            row.status = "expired"  # 一次只让用户做一个决定：新卡替掉旧卡


def _save_card(session, user_id: str, card: dict[str, Any], day: str) -> AgentAction:
    card.update({"plan_line": True, "day": day, "label": BADGE})
    row = AgentAction(
        id=f"{user_id}:goal:{uuid.uuid4().hex[:10]}",
        user_id=user_id,
        trigger="goal_setup",
        suggestion_json=json.dumps(card, ensure_ascii=False),
        status="pending",
        before_json="{}",
        after_json="{}",
    )
    session.add(row)
    return row


def draft(user_id: str, answers: dict[str, Any]) -> dict[str, Any]:
    service.ensure_today_plan(user_id)
    today = service.today_for(user_id)
    values, chosen, unclear = normalize(answers, today)
    with SessionLocal() as session:
        _expire_pending(session, user_id)
        row = _save_card(session, user_id, build_card(values, chosen, today), today.isoformat())
        session.commit()
        session.refresh(row)
        data = card_view(row)
    data["unclear"] = unclear
    return data


def revise(user_id: str, action_id: str, text: str) -> Optional[dict[str, Any]]:
    today = service.today_for(user_id)
    with SessionLocal() as session:
        row = session.get(AgentAction, action_id)
        if not service._is_plan_card(row, user_id) or service._card_meta(row).get("kind") != KIND_GOAL_SETUP:
            return None
        if row.status not in ("pending", "executed"):
            raise service.CardError("这张卡已经换成新的了")
        changes = parse.revise(text, today)
        if "exam_date" in changes and changes["exam_date"] not in (parse.NO_DATE, None):
            if date.fromisoformat(changes["exam_date"]) <= today:
                changes.pop("exam_date")
        if not changes:
            raise service.CardError("没听懂要改哪一项，可以说“考试改到 12 月 20 日”“一共 10 讲”“学到第 3 讲”或“每天只有 20 分钟”")
        meta = service._card_meta(row)
        values = dict(meta.get("values") or DEFAULTS)
        chosen = dict(meta.get("chosen") or {})
        for key, value in changes.items():
            values[key] = None if value == parse.NO_DATE else value
            chosen[key] = True
        if "daily_minutes" in changes and "intensity" not in changes:
            values.pop("intensity", None)
            chosen.pop("intensity", None)
        values["learned_up_to"] = min(int(values["learned_up_to"]), int(values["lecture_count"]))
        if row.status == "pending":
            row.status = "revised"
        _expire_pending(session, user_id)
        new_row = _save_card(session, user_id, build_card(values, chosen, today), today.isoformat())
        session.commit()
        session.refresh(new_row)
        data = card_view(new_row)
    data["changed"] = sorted(changes)
    return data


def _goal_snapshot(goal: Goal, plan: PlanDay) -> dict[str, Any]:
    return {
        "title": goal.title,
        "exam_date": goal.exam_date,
        "status": goal.status,
        "lecture_count": goal.lecture_count,
        "daily_minutes": goal.daily_minutes,
        "summary_json": goal.summary_json,
        "intensity": plan.intensity,
    }


def accept(user_id: str, action_id: str) -> Optional[dict[str, Any]]:
    """点“好”：目标生效，今天的三件按新目标重排。"""
    plan_id = service.ensure_today_plan(user_id)
    today = service.today_for(user_id)
    with SessionLocal() as session:
        row = session.get(AgentAction, action_id)
        if not service._is_plan_card(row, user_id):
            return None
        if row.status != "pending":
            raise service.CardError("这张卡已经处理过了")
        meta = service._card_meta(row)
        values, chosen, plan_info = meta["values"], meta["chosen"], meta["breakdown"]
        goal = session.scalar(select(Goal).where(Goal.user_id == user_id))
        plan = session.get(PlanDay, plan_id)
        assert goal is not None and plan is not None
        before = _goal_snapshot(goal, plan)

        goal.title = str(values["title"])[:200]
        goal.exam_date = values.get("exam_date") or ""
        goal.lecture_count = int(values["lecture_count"])
        goal.daily_minutes = int(values["daily_minutes"])
        goal.status = "active"
        summary = service._loads(goal.summary_json, {})
        summary.pop("pace", None)
        summary.update(
            {
                "confirmed": True,
                "learned_up_to": int(values["learned_up_to"]),
                "chosen": chosen,
                "phases": plan_info["phases"],
                "review_floor": plan_info["review_floor"],
                "default_intensity": plan_info["default_intensity"],
                "label": BADGE,
            }
        )
        goal.summary_json = json.dumps(summary, ensure_ascii=False)
        plan.intensity = plan_info["default_intensity"]

        meta["chosen_option"] = "ok"
        row.suggestion_json = json.dumps(meta, ensure_ascii=False)
        row.status = "executed"
        row.before_json = json.dumps(before, ensure_ascii=False)
        row.after_json = json.dumps(_goal_snapshot(goal, plan), ensure_ascii=False)
        service._rebuild_today(session, user_id, plan, today)
        session.commit()
        session.refresh(row)
        data = card_view(row)
    data["plan"] = service.plan_today(user_id)
    data["goal"] = current(user_id)
    return data


def undo(user_id: str, action_id: str) -> Optional[dict[str, Any]]:
    """撤销：目标回到点“好”之前；第一次定目标被撤销时，左栏清空。"""
    plan_id = service.ensure_today_plan(user_id)
    today = service.today_for(user_id)
    with SessionLocal() as session:
        row = session.get(AgentAction, action_id)
        if not service._is_plan_card(row, user_id):
            return None
        if row.status != "executed":
            raise service.CardError("这张卡还没生效，不用撤销")
        goal = session.scalar(select(Goal).where(Goal.user_id == user_id))
        plan = session.get(PlanDay, plan_id)
        assert goal is not None and plan is not None
        before = service._loads(row.before_json, {})
        for key in ("title", "exam_date", "lecture_count", "daily_minutes", "summary_json"):
            setattr(goal, key, before.get(key, getattr(goal, key)))
        goal.status = before.get("status") or goal.status
        if not service._loads(goal.summary_json, {}).get("confirmed"):
            goal.status = "draft"  # 之前没定过目标：撤销后不排任务
        plan.intensity = before.get("intensity") or service.DEFAULT_INTENSITY
        row.status = "undone"
        service._rebuild_today(session, user_id, plan, today)
        session.commit()
        session.refresh(row)
        data = card_view(row)
    data["plan"] = service.plan_today(user_id)
    data["goal"] = current(user_id)
    return data


def card_view(row: AgentAction) -> dict[str, Any]:
    data = service._card_view(row)
    meta = service._card_meta(row)
    data["revise_label"] = meta.get("revise_label", "说说怎么改")
    data["defaults_used"] = [key for key in FIELDS if not (meta.get("chosen") or {}).get(key)]
    return data


# ---------- 目标本身 ----------


def _goal_view(goal: Goal) -> dict[str, Any]:
    summary = service._loads(goal.summary_json, {})
    return {
        "id": goal.id,
        "title": goal.title,
        "exam_date": goal.exam_date,
        "status": goal.status,
        "lecture_count": goal.lecture_count,
        "daily_minutes": goal.daily_minutes,
        "learned_up_to": summary.get("learned_up_to"),
        "phases": summary.get("phases", []),
        "review_floor": summary.get("review_floor", returning.REVIEW_FLOOR_DAYS),
        "default_intensity": summary.get("default_intensity", service.DEFAULT_INTENSITY),
        "chosen": summary.get("chosen", {}),
        "needs_setup": needs_setup(goal),
        "summary": summary,
        "card_type": "goal",
        "label": BADGE,
    }


def needs_setup(goal: Optional[Goal]) -> bool:
    return service.needs_setup(goal)


def current(user_id: str) -> dict[str, Any]:
    store.seed(user_id)
    with SessionLocal() as session:
        goal = session.scalar(select(Goal).where(Goal.user_id == user_id))
        assert goal is not None
        return _goal_view(goal)


def save_direct(user_id: str, *, title: str, exam_date: str, lecture_count: int, daily_minutes: int) -> dict[str, Any]:
    """用户自己直接改目标（不经过卡片）：直接生效，保留计划线记下的进度等信息。"""
    store.seed(user_id)
    with SessionLocal() as session:
        goal = session.scalar(select(Goal).where(Goal.user_id == user_id))
        assert goal is not None
        summary = service._loads(goal.summary_json, {})
        chosen = dict(summary.get("chosen") or {})
        if title:
            goal.title, chosen["title"] = title[:200], True
        goal.exam_date = (exam_date or "")[:32]
        chosen["exam_date"] = True
        if lecture_count > 0:
            goal.lecture_count, chosen["lecture_count"] = lecture_count, True
        if daily_minutes > 0:
            goal.daily_minutes, chosen["daily_minutes"] = daily_minutes, True
        if goal.status == "draft":
            goal.status = "active"
        summary["chosen"] = chosen
        goal.summary_json = json.dumps(summary, ensure_ascii=False)
        session.commit()
        session.refresh(goal)
        return _goal_view(goal)
