"""F8 只读聚合。读取计划/练习线的记录，不创建或调整计划。"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import json
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.data_access.session import SessionLocal
from app.study.common.db import ensure_schema
from app.study.common.models import (
    Attempt, Chapter, Course, Goal, KnowledgePoint, LlmCall,
    PlanTask, Question, StudyEvent, StudyFile,
)

TZ = ZoneInfo("Asia/Shanghai")


def decode(raw: str, default=None):
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return default


def mapping(raw: str) -> dict:
    value = decode(raw)
    return value if isinstance(value, dict) else {}


def parse_date(raw) -> date | None:
    try:
        return date.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


def parse_instant(raw: str) -> datetime | None:
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return value.replace(tzinfo=value.tzinfo or timezone.utc)
    except (ValueError, TypeError, AttributeError):
        return None


def local_day(raw: str) -> date | None:
    value = parse_instant(raw)
    return value.astimezone(TZ).date() if value else None


def instant(raw: str) -> float:
    value = parse_instant(raw)
    return value.timestamp() if value else float("-inf")


def _saved_progress(goal: Goal | None, learned: set[str], today: date) -> dict | None:
    if goal is None:
        return None
    summary = mapping(goal.summary_json)
    total = max(0, goal.lecture_count)
    count = summary.get("learned_up_to")
    saved = isinstance(count, int) and not isinstance(count, bool) and count >= 0
    count = min(total, count if saved else len(learned))
    if goal.status == "done":
        count = total
    phase = ""
    phases = summary.get("phases")
    phase_unavailable = phases is not None and not isinstance(phases, list)
    for item in phases if isinstance(phases, list) else []:
        if not isinstance(item, dict):
            phase_unavailable = True
            continue
        start, end = parse_date(item.get("start")), parse_date(item.get("end"))
        if not start or not end or end < start:
            phase_unavailable = True
            continue
        if start <= today <= end:
            phase = str(item.get("name") or "")
    exam = parse_date(goal.exam_date)
    return {
        "today": today.isoformat(), "learned_up_to": count, "lecture_count": total,
        "goal_progress": round(count / total, 4) if total else 0,
        "source": "plan_saved_progress" if saved else "completed_learning_records",
        "phase": phase, "phase_unavailable": phase_unavailable, "goal_status": goal.status,
        "days_to_exam": (exam - today).days if exam else None,
    }


def snapshot(user_id: str, *, today: date | None = None) -> dict:
    ensure_schema()
    clock_label = ""
    if today is None:
        from app.study.plan import demo
        offset = demo.offset_days(user_id)
        today = demo.real_today() + timedelta(days=offset)
        if offset:
            clock_label = " · 演示用"
    start = today - timedelta(days=today.weekday())
    with SessionLocal() as session:
        def rows(model):
            return session.scalars(select(model).where(model.user_id == user_id)).all()

        attempts = [(row, parse_instant(row.created_at)) for row in rows(Attempt)]
        attempts = [(row, at) for row, at in attempts if at and at.astimezone(TZ).date() <= today]
        attempts.sort(key=lambda pair: (pair[1].timestamp(), pair[0].id))
        weekly = [(row, at.astimezone(TZ).date()) for row, at in attempts
                  if start <= at.astimezone(TZ).date() <= today]
        latest = {row.question_id: row for row, _ in attempts}
        questions = {q.id: q for q in rows(Question)}
        pending = [row for qid, row in latest.items() if qid in questions and not row.correct]
        events, tasks = rows(StudyEvent), rows(PlanTask)
        task_days = {task.id: parse_date(task.day) for task in tasks}
        activity = {day for _, day in weekly}
        completed_ids = set()
        for event in events:
            props = mapping(event.props_json)
            if event.name == "task_status" and props.get("status") == "done":
                task_id = props.get("task_id")
                if not isinstance(task_id, str):
                    continue
                day = task_days.get(task_id) or local_day(event.at)
                completed_ids.add(task_id)
            elif event.name in ("study_completed", "lecture_completed"):
                day = local_day(event.at)
            else:
                continue
            if day and start <= day <= today:
                activity.add(day)
        for task in tasks:
            day = task_days[task.id]
            if task.status == "done" and task.id not in completed_ids and day and start <= day <= today:
                activity.add(day)

        points = rows(KnowledgePoint)
        chapters = sorted(rows(Chapter), key=lambda row: (row.sort_order, row.id))
        files = sorted(rows(StudyFile), key=lambda row: (row.created_at, row.id))
        values_by_lecture = defaultdict(list)
        for point in points:
            if point.lecture_id:
                values_by_lecture[point.lecture_id].append(min(100, max(0, point.mastery)))
        pending_by_lecture = defaultdict(int)
        for attempt in pending:
            pending_by_lecture[questions[attempt.question_id].lecture_id] += 1
        titles = {}
        for chapter in chapters:
            if chapter.lecture_id:
                titles.setdefault(chapter.lecture_id, chapter.title or chapter.lecture_id)
        # Newly uploaded lectures may have no Chapter yet. Keep their records visible.
        for file in files:
            if file.lecture_id:
                titles.setdefault(file.lecture_id, file.filename or file.lecture_id)
        for lecture_id in sorted(values_by_lecture):
            titles.setdefault(lecture_id, lecture_id)
        lectures = []
        for lecture_id, title in titles.items():
            values = values_by_lecture[lecture_id]
            lectures.append({
                "id": lecture_id, "title": title,
                "mastery": round(sum(values) / len(values)) if values else 0,
                "assessed": bool(values), "mistakes_due": pending_by_lecture[lecture_id],
            })

        goals = sorted(rows(Goal), key=lambda row: (instant(row.created_at), row.id), reverse=True)
        goal = next((row for row in goals if row.status in ("active", "paused", "done")), None)
        course_ids = {course.id for course in rows(Course) if goal and course.goal_id == goal.id}
        goal_lectures = {chapter.lecture_id for chapter in chapters if chapter.course_id in course_ids}
        learned = set()
        for task in tasks:
            ref, day = mapping(task.ref_json), task_days[task.id]
            lecture_id = ref.get("lecture_id")
            if (task.kind == "learn" and task.status == "done" and day and day <= today
                    and isinstance(lecture_id, str) and lecture_id in goal_lectures):
                learned.add(lecture_id)
        plan_metrics = _saved_progress(goal, learned, today)
        total = plan_metrics["lecture_count"] if plan_metrics else 0
        count = plan_metrics["learned_up_to"] if plan_metrics else 0
        mock = any(event.name == "foundation_seed" for event in events)
        return {
            "range": "week", "period": {"start": start.isoformat(), "end": today.isoformat(), "timezone": "Asia/Shanghai"},
            "studied_days": len(activity), "attempt_count": len(weekly), "mistakes_due": len(pending),
            "lectures": lectures,
            "files": [{"id": file.id, "filename": file.filename, "parse_status": file.parse_status} for file in files],
            "goal_progress": plan_metrics["goal_progress"] if plan_metrics else 0,
            "goal": {"title": goal.title if goal else "", "completed_lectures": count,
                     "total_lectures": total, "status": goal.status if goal else ""},
            "plan_progress": plan_metrics,
            "llm_calls": session.scalar(select(func.count(LlmCall.id)).where(LlmCall.user_id == user_id)) or 0,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "label": ("模拟" if mock else "学习记录统计") + clock_label,
            "mock": mock, "note": "只和自己的过去比。做过的学习都会留下记录。",
            "mastery_note": "尚未评估的讲次会在做题后显示掌握度。",
        }


def summary_card(data: dict) -> dict:
    return {
        "type": "dashboard", "title": "这周的学习", "label": data["label"],
        "text": f"这周学了 {data['studied_days']} 天，做了 {data['attempt_count']} 道题，待重做 {data['mistakes_due']} 道。",
        "goal_progress": data["goal_progress"], "action": "打开完整看板",
    }
