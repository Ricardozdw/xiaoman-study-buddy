"""F8 只读聚合。掌握度由练习线写入，看板不改学习记录。"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.data_access.session import SessionLocal
from app.study.common.db import ensure_schema
from app.study.common.models import (
    Attempt, Chapter, Course, Goal, KnowledgePoint, LlmCall,
    PlanDay, PlanTask, Question, StudyEvent, StudyFile,
)

TZ = ZoneInfo("Asia/Shanghai")


def decode(raw: str, default=None):
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return default


def local_day(raw: str) -> date | None:
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(TZ).date()
    except (ValueError, TypeError, AttributeError):
        return None


def instant(raw: str) -> float:
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return value.replace(tzinfo=value.tzinfo or timezone.utc).timestamp()
    except (ValueError, TypeError, AttributeError):
        return float("-inf")


def snapshot(user_id: str, *, today: date | None = None) -> dict:
    ensure_schema()
    plan_metrics = None
    clock_label = ""
    if today is None:
        from app.study.plan import demo, progress as plan_progress
        today = demo.today(user_id)
        if demo.offset_days(user_id):
            clock_label = " · 演示用"
        # Reuse the plan owner's progress contract only for existing plans.
        # An empty read must not create the foundation's sample target/tasks.
        with SessionLocal() as probe:
            saved_goal = probe.scalar(select(Goal).where(Goal.user_id == user_id))
            has_plan = probe.scalar(select(PlanDay.id).where(PlanDay.user_id == user_id))
            saved_summary = decode(saved_goal.summary_json, {}) if saved_goal else {}
            saved_total = saved_goal.lecture_count if saved_goal else 0
        if saved_goal and has_plan:
            # The foundation stores phases as strings; the plan endpoint expects
            # objects. Keep that legacy fixture readable without editing its owner.
            phases = saved_summary.get("phases", []) if isinstance(saved_summary, dict) else []
            structured = isinstance(phases, list) and all(isinstance(p, dict) for p in phases)
            if structured:
                plan_metrics = plan_progress.progress(user_id)
            else:
                learned_up_to = saved_summary.get("learned_up_to", 0)
                learned_up_to = learned_up_to if isinstance(learned_up_to, int) else 0
                plan_metrics = {"today": today.isoformat(), "learned_up_to": learned_up_to,
                                "lecture_count": saved_total,
                                "goal_progress": round(learned_up_to / saved_total, 3) if saved_total else 0,
                                "source": "plan_saved_progress", "phase_unavailable": True}
    start = today - timedelta(days=today.weekday())
    with SessionLocal() as session:
        def rows(model):
            return session.scalars(select(model).where(model.user_id == user_id)).all()

        attempts = sorted(rows(Attempt), key=lambda r: (instant(r.created_at), r.id))
        visible = [a for a in attempts if local_day(a.created_at) and local_day(a.created_at) <= today]
        weekly = [a for a in visible if start <= local_day(a.created_at) <= today]
        latest = {a.question_id: a for a in visible}
        questions = {q.id: q for q in rows(Question)}
        pending = [a for qid, a in latest.items() if qid in questions and not a.correct]
        events, tasks = rows(StudyEvent), rows(PlanTask)
        task_days = {task.id: task.day for task in tasks}
        activity = {local_day(a.created_at) for a in weekly}
        completed_ids = set()
        for event in events:
            props = decode(event.props_json, {})
            if not isinstance(props, dict):
                continue
            if event.name == "task_status" and props.get("status") == "done":
                # Demo task days can differ from the real event timestamp.
                try:
                    day = date.fromisoformat(task_days.get(props.get("task_id"), ""))
                except ValueError:
                    day = local_day(event.at)
                if day and start <= day <= today:
                    activity.add(day)
                completed_ids.add(props.get("task_id"))
            elif event.name in ("study_completed", "lecture_completed"):
                day = local_day(event.at)
                if day and start <= day <= today:
                    activity.add(day)
        for task in tasks:
            if task.status == "done" and task.id not in completed_ids:
                try:
                    day = date.fromisoformat(task.day)
                except ValueError:
                    continue
                if start <= day <= today:
                    activity.add(day)

        points = rows(KnowledgePoint)
        chapters = sorted(rows(Chapter), key=lambda r: (r.sort_order, r.id))
        lectures = []
        for chapter in chapters:
            values = [min(100, max(0, p.mastery)) for p in points if p.lecture_id == chapter.lecture_id]
            lectures.append({
                "id": chapter.lecture_id, "title": chapter.title,
                "mastery": round(sum(values) / len(values)) if values else 0,
                "assessed": bool(values),
                "mistakes_due": sum(questions[a.question_id].lecture_id == chapter.lecture_id for a in pending),
            })
        goals = sorted(rows(Goal), key=lambda r: (r.created_at, r.id), reverse=True)
        goal = next((g for g in goals if g.status in ("active", "done")), None)
        goal_courses = {c.id for c in rows(Course) if goal and c.goal_id == goal.id}
        goal_lectures = {c.lecture_id for c in chapters if c.course_id in goal_courses}
        learned = set()
        for task in tasks:
            ref = decode(task.ref_json, {})
            if (task.kind == "learn" and task.status == "done" and task.day <= today.isoformat()
                    and isinstance(ref, dict) and ref.get("lecture_id") in goal_lectures):
                learned.add(ref["lecture_id"])
        total = max(0, goal.lecture_count) if goal else 0
        progress = min(1, len(learned) / total) if total else 0
        if goal and goal.status == "done":
            progress = 1
        completed_count = len(learned)
        if plan_metrics:
            progress = min(1, max(0, plan_metrics["goal_progress"]))
            completed_count = plan_metrics["learned_up_to"]
            total = plan_metrics["lecture_count"]
        mock = any(e.name == "foundation_seed" for e in events)
        return {
            "range": "week", "period": {"start": start.isoformat(), "end": today.isoformat(), "timezone": "Asia/Shanghai"},
            "studied_days": len(activity), "attempt_count": len(weekly), "mistakes_due": len(pending),
            "lectures": lectures,
            "files": [{"id": f.id, "filename": f.filename, "parse_status": f.parse_status} for f in rows(StudyFile)],
            "goal_progress": round(progress, 4), "goal": {
                "title": goal.title if goal else "", "completed_lectures": completed_count, "total_lectures": total,
            },
            "plan_progress": plan_metrics,
            "llm_calls": len(rows(LlmCall)), "label": ("模拟" if mock else "学习记录统计") + clock_label,
            "mock": mock, "note": "只和自己的过去比。做过的学习都会留下记录。",
            "mastery_note": "掌握度取练习线保存的知识点平均值；尚未评估的讲次显示为未评估。",
        }


def summary_card(data: dict) -> dict:
    return {
        "type": "dashboard", "title": "这周的学习", "label": data["label"],
        "text": f"这周学了 {data['studied_days']} 天，做了 {data['attempt_count']} 道题，待重做 {data['mistakes_due']} 道。",
        "goal_progress": data["goal_progress"], "action": "打开完整看板",
    }
