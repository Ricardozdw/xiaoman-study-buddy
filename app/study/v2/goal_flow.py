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


ORDER = ["deadline", "minutes", "materials", "progress"]
RETRY_HINT = {
    "deadline": "没太听懂完成时间，可以点下面的选项，或直接说“两周”“12 月底”。",
    "minutes": "没太听懂每天的时间，可以点下面的选项，或直接说“半小时”“1 小时”。",
    "materials": "可以点下面的选项告诉我有没有资料。",
}


def _question(step, *, ack="", retry=False):
    q = dict(QUESTIONS[step])
    if retry and step in RETRY_HINT:
        q["question"] = f"{RETRY_HINT[step]}\n{q['question']}"
    elif ack:
        q["question"] = f"{ack}\n{q['question']}"
    return q


def _next_step(p):
    for step in ORDER:
        if step == "deadline" and p.get("deadline_text") is None:
            return step
        if step == "minutes" and p.get("daily_minutes") is None:
            return step
        if step == "materials" and not p.get("materials_known", p.get("step") in ("progress", "done")):
            return step
        if step == "progress" and not p.get("progress"):
            return step
    return "done"


def prefill(text, user_id):
    """从用户开口那句话里先拿出已经说过的信息，免得再问一遍。"""
    found = {}
    d, dt = _find_deadline(text, user_id)
    if dt is not None:
        found["deadline"], found["deadline_text"] = d, dt
    m = _find_minutes(text)
    if m is not None:
        found["daily_minutes"] = m
    if re.search(r"零基础|刚开始|没学过|从头|小白|新手", text):
        found["progress"] = "刚开始"
    return found


# 与 v2.service 定档一致：≤20 轻松（约 15 分钟）/ ≤40 正常（约 30）/ 其余 冲刺（约 50）。
TIERS = [("轻松", 15), ("正常", 30), ("冲刺", 50)]


def tier_for(minutes):
    return TIERS[0] if minutes <= 20 else TIERS[1] if minutes <= 40 else TIERS[2]


def minutes_note(minutes):
    """用户说的分钟数不正好是某一档时，说清楚按哪一档排、怎么改；正好是一档就不多说。"""
    if not minutes:
        return ""
    label, tier = tier_for(minutes)
    if minutes == tier:
        return ""
    head = f"每天 {minutes} 分钟——我先按「{label}」排，每天约 {tier} 分钟"
    index = [name for name, _ in TIERS].index(label)
    if minutes > tier and index + 1 < len(TIERS):
        up, up_min = TIERS[index + 1]
        return f"{head}；想多学点，可以在「今天」里改成「{up}」（约 {up_min} 分钟）。"
    if minutes < tier:
        return f"{head}；时间不够的那天，做完一部分也算。"
    return f"{head}，这是最多的一档。"


def _ack(found):
    parts = []
    if found.get("deadline_text"):
        parts.append(f"完成时间：{found['deadline_text']}")
    if found.get("daily_minutes"):
        parts.append(f"每天 {found['daily_minutes']} 分钟")
    if found.get("progress"):
        parts.append(f"进度：{found['progress']}")
    text = f"好，记下了：{'，'.join(parts)}。" if parts else ""
    note = minutes_note(found.get("daily_minutes"))
    return f"{text}\n{note}" if text and note else text


def start(user_id, goal_type, title, message=""):
    """开始一轮对话式定目标，返回第一个还没答的问题（用户开口已说过的不再问）。"""
    ensure_schema()
    from app.study.common import store
    store.seed(user_id)
    found = prefill(message, user_id) if message else {}
    p = {"goal_type": goal_type, "title": title,
         "deadline": None, "deadline_text": None,
         "daily_minutes": None, "materials": "none", "materials_known": False,
         "progress": "", "step": "deadline"}
    p.update(found)
    p["step"] = _next_step(p)
    with SessionLocal() as session:
        _save(session, user_id, p)
        session.commit()
    return _question(p["step"], ack=_ack(found))


CN_NUM = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "半": 0.5}


def _num(token):
    if token is None:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", token):
        return float(token)
    if token in CN_NUM:
        return CN_NUM[token]
    if re.fullmatch(r"十[一二三四五六七八九]", token):
        return 10 + CN_NUM[token[1]]
    if re.fullmatch(r"[一二两三四五六七八九]十[一二三四五六七八九]?", token):
        return CN_NUM[token[0]] * 10 + (CN_NUM[token[2]] if len(token) == 3 else 0)
    return None


NUM = r"(\d+(?:\.\d+)?|[一二两三四五六七八九]?十[一二三四五六七八九]?|[一二两三四五六七八九半])"


def _find_deadline(text, user_id):
    t = text.strip()
    today = plan_service.today_for(user_id)
    if re.search(r"不急|慢慢来|没有截止|没截止", t):
        return None, "不急"
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", t)
    if m:
        try:
            d = today.replace(year=int(m.group(1)), month=int(m.group(2)), day=int(m.group(3)))
            return d.isoformat(), d.isoformat()
        except ValueError:
            pass
    m = re.search(r"(\d{1,2})\s*月\s*(?:(\d{1,2})\s*[日号]|(底|初|中))", t)
    if m:
        month = int(m.group(1))
        day = int(m.group(2)) if m.group(2) else {"初": 5, "中": 15, "底": 28}[m.group(3)]
        try:
            d = today.replace(month=month, day=day)
            if d < today:
                d = d.replace(year=today.year + 1)
            return d.isoformat(), f"{month} 月{m.group(2) + ' 日' if m.group(2) else m.group(3)}（{d.isoformat()}）"
        except ValueError:
            pass
    if "年底" in t:
        d = today.replace(month=12, day=31)
        return d.isoformat(), f"年底（{d.isoformat()}）"
    if "下个月" in t:
        d = today + timedelta(days=30)
        return d.isoformat(), f"一个月内（{d.isoformat()}）"
    if "半个月" in t or "半月" in t:
        d = today + timedelta(days=15)
        return d.isoformat(), f"半个月（{d.isoformat()}）"
    m = re.search(NUM + r"\s*个?\s*(天|日|周|星期|礼拜|个月|月)", t)
    if m:
        n = _num(m.group(1))
        unit = m.group(2)
        if n:
            days = n * (7 if unit in ("周", "星期", "礼拜") else 30 if unit in ("个月", "月") else 1)
            if 1 <= days <= 3650:
                d = today + timedelta(days=int(round(days)))
                label = f"{m.group(1)}{'个' if unit == '月' else ''}{unit}"
                return d.isoformat(), f"{label}（{d.isoformat()}）"
    return None, None


def _find_minutes(text):
    t = text.strip().lower()
    if "一个半小时" in t or "一个半钟头" in t:
        return 90
    if "一刻钟" in t:
        return 15
    if re.search(r"半(个)?(小时|钟头)", t) and not re.search(NUM + r"\s*个?半?\s*(小时|钟头)", t.replace("半小时", "").replace("半个小时", "")):
        return 30
    m = re.search(NUM + r"\s*个?(半)?\s*(小时|钟头|h\b|hour)", t)
    if m:
        n = _num(m.group(1))
        if n:
            v = int(round((n + (0.5 if m.group(2) else 0)) * 60))
            return v if 5 <= v <= 600 else None
    m = re.search(NUM + r"\s*(分钟|分|min)", t)
    if m:
        n = _num(m.group(1))
        if n and 5 <= n <= 600:
            return int(n)
    return None


def _parse_deadline(text, user_id):
    t = text.strip()
    if t == "一个月内":
        d = plan_service.today_for(user_id) + timedelta(days=30)
        return d.isoformat(), f"一个月内（{d.isoformat()}）"
    if t == "三个月内":
        d = plan_service.today_for(user_id) + timedelta(days=90)
        return d.isoformat(), f"三个月内（{d.isoformat()}）"
    return _find_deadline(t, user_id)


def _parse_minutes(text):
    m = re.fullmatch(r"(\d{1,3})\s*(?:分钟)?", text.strip())
    if m:
        v = int(m.group(1))
        return v if 5 <= v <= 600 else None
    return _find_minutes(text)


def _parse_materials(text):
    t = text.strip()
    if t in ("没有", "无", "没"):
        return "none"
    if t in ("有，现在交", "现在交", "现在"):
        return "now"
    if t in ("有，晚点交", "晚点交", "晚点", "以后交"):
        return "later"
    if re.search(r"晚点|以后|过几天|回头", t):
        return "later"
    if re.search(r"^(没|无|不)|没有", t):
        return "none"
    if re.search(r"有|现在|马上", t):
        return "now"
    return None


def advance(user_id, answer):
    """处理用户在对话里的回答。返回 (next_question 或 None, outline 或 None)。

    没听懂时返回同一个问题重问；全部答完时生成大纲并清空进行中状态。
    """
    ack = ""  # 答了每天时间、且不正好是某一档时，下一问前面先说明按哪档排
    with SessionLocal() as session:
        goal, p = _read(session, user_id)
        if goal is None or p is None:
            return None, None
        step = p["step"]
        if step == "deadline":
            d, dt = _parse_deadline(answer, user_id)
            if d is None and dt is None:
                return _question("deadline", retry=True), None
            p["deadline"], p["deadline_text"] = d, dt
        elif step == "minutes":
            m = _parse_minutes(answer)
            if m is None:
                return _question("minutes", retry=True), None
            p["daily_minutes"] = m
            ack = minutes_note(m)
        elif step == "materials":
            m = _parse_materials(answer)
            if m is None:
                return _question("materials", retry=True), None
            p["materials"], p["materials_known"] = m, True
        elif step == "progress":
            p["progress"] = answer.strip()[:1000] or "刚开始"
        else:
            return None, None
        p["step"] = _next_step(p)
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
        return _question(p["step"], ack=ack), None
