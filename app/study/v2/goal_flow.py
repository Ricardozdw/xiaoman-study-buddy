"""对话式定目标：把目标卡片里的提问（完成时间→每天时间→资料→进度）搬到对话里，一次一问。"""
from __future__ import annotations

import json
import re
from datetime import timedelta

from sqlalchemy import select

from app.data_access.session import SessionLocal
from app.study.common.db import ensure_schema
from app.study.common.models import Goal
from app.study.plan import service as plan_service

PENDING_KEY = "v2_goal_pending"

QUESTIONS = {
    "deadline": {"question": "什么时候想完成？", "options": ["一个月内", "三个月内", "不急"], "step": "deadline"},
    "minutes": {"question": "每天大概有多少时间？", "options": ["15 分钟", "30 分钟", "50 分钟"], "step": "minutes"},
    "materials": {"question": "手上有课件、教材或考纲吗？", "options": ["有，现在交", "有，晚点交", "没有"], "step": "materials"},
    "progress": {"question": "学到哪了？", "options": ["刚开始", "学了一部分", "快学完了"], "step": "progress"},
}


def _read(session, user_id):
    goal = session.scalar(select(Goal).where(Goal.user_id == user_id))
    if goal is None:
        return None, None
    data = json.loads(goal.summary_json or "{}")
    return goal, data.get(PENDING_KEY)


def pending(user_id):
    """当前是否有进行中的定目标（没有则返回 None）。"""
    with SessionLocal() as session:
        _, p = _read(session, user_id)
        return p


def _save(session, user_id, p):
    goal, _ = _read(session, user_id)
    assert goal is not None
    data = json.loads(goal.summary_json or "{}")
    data[PENDING_KEY] = p
    goal.summary_json = json.dumps(data, ensure_ascii=False)


def start(user_id, goal_type, title):
    """开始一轮对话式定目标，返回第一个问题。"""
    ensure_schema()
    from app.study.common import store
    store.seed(user_id)
    with SessionLocal() as session:
        _save(session, user_id, {"goal_type": goal_type, "title": title,
                                 "deadline": None, "deadline_text": None,
                                 "daily_minutes": None, "materials": "none",
                                 "progress": "", "step": "deadline"})
        session.commit()
    return QUESTIONS["deadline"]


def _parse_deadline(text, user_id):
    t = text.strip()
    if t == "一个月内":
        d = plan_service.today_for(user_id) + timedelta(days=30)
        return d.isoformat(), f"一个月内（{d.isoformat()}）"
    if t == "三个月内":
        d = plan_service.today_for(user_id) + timedelta(days=90)
        return d.isoformat(), f"三个月内（{d.isoformat()}）"
    if t == "不急":
        return None, "不急"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
        return t, t
    return None, None


def _parse_minutes(text):
    m = re.fullmatch(r"(\d{1,3})\s*(?:分钟)?", text.strip())
    if not m:
        return None
    v = int(m.group(1))
    return v if 5 <= v <= 600 else None


def _parse_materials(text):
    t = text.strip()
    if t in ("没有", "无", "没"):
        return "none"
    if t in ("有，现在交", "现在交", "现在"):
        return "now"
    if t in ("有，晚点交", "晚点交", "晚点", "以后交"):
        return "later"
    return None


def advance(user_id, answer):
    """处理用户在对话里的回答。返回 (next_question 或 None, outline 或 None)。

    没听懂时返回同一个问题重问；全部答完时生成大纲并清空进行中状态。
    """
    with SessionLocal() as session:
        goal, p = _read(session, user_id)
        if goal is None or p is None:
            return None, None
        step = p["step"]
        if step == "deadline":
            d, dt = _parse_deadline(answer, user_id)
            if d is None and dt is None:
                return QUESTIONS["deadline"], None
            p["deadline"], p["deadline_text"], p["step"] = d, dt, "minutes"
        elif step == "minutes":
            m = _parse_minutes(answer)
            if m is None:
                return QUESTIONS["minutes"], None
            p["daily_minutes"], p["step"] = m, "materials"
        elif step == "materials":
            m = _parse_materials(answer)
            if m is None:
                return QUESTIONS["materials"], None
            p["materials"], p["step"] = m, "progress"
        elif step == "progress":
            p["progress"], p["step"] = answer.strip()[:1000], "done"
        else:
            return None, None
        _save(session, user_id, p)
        session.commit()
        if p["step"] == "done":
            from app.study.v2 import service as v2_service
            outline = v2_service.draft(user_id, {
                "goal_type": p["goal_type"], "title": p["title"],
                "deadline": p["deadline"], "daily_minutes": p["daily_minutes"] or 30,
                "progress": p["progress"], "materials": p["materials"],
            })
            with SessionLocal() as s2:
                g2, _ = _read(s2, user_id)
                d2 = json.loads(g2.summary_json or "{}")
                d2.pop(PENDING_KEY, None)
                g2.summary_json = json.dumps(d2, ensure_ascii=False)
                s2.commit()
            return None, outline
        return QUESTIONS[p["step"]], None
