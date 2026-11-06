"""给看板线的计划数据：这周学了几天、目标进度、现在在哪个阶段。

只和自己的过去比；不做“连续 N 天”。看板线读这里，不用自己算计划线的规则。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select

from app.data_access.session import SessionLocal
from app.study.common.models import Goal, PlanDay, PlanTask
from app.study.plan import service


def _phase_now(phases: list[dict[str, Any]], today: date) -> str:
    for phase in phases or []:
        start, end = phase.get("start"), phase.get("end")
        if start and end and date.fromisoformat(start) <= today <= date.fromisoformat(end):
            return str(phase.get("name") or "")
    return ""


def progress(user_id: str) -> dict[str, Any]:
    service.ensure_today_plan(user_id)
    today = service.today_for(user_id)
    week_start = today - timedelta(days=today.weekday())  # 周一
    with SessionLocal() as session:
        goal = session.scalar(select(Goal).where(Goal.user_id == user_id))
        days = session.scalars(
            select(PlanDay).where(
                PlanDay.user_id == user_id, PlanDay.day >= week_start.isoformat(), PlanDay.day <= today.isoformat()
            )
        ).all()
        studied, done_count = set(), 0
        for plan in days:
            done = session.scalars(
                select(PlanTask).where(PlanTask.plan_day_id == plan.id, PlanTask.user_id == user_id, PlanTask.status == "done")
            ).all()
            if done:
                studied.add(plan.day)
                done_count += len(done)
        summary = service._loads(goal.summary_json, {}) if goal else {}
        learned = summary.get("learned_up_to")
        learned = learned if isinstance(learned, int) else 0
        count = goal.lecture_count if goal else 0
        exam = service._local_date(goal.exam_date) if goal else None
        return {
            "today": today.isoformat(),
            "week_start": week_start.isoformat(),
            "studied_days_this_week": len(studied),
            "done_tasks_this_week": done_count,
            "learned_up_to": learned,
            "lecture_count": count,
            "goal_progress": round(learned / count, 3) if count else 0,
            "exam_date": goal.exam_date if goal else "",
            "days_to_exam": (exam - today).days if exam else None,
            "phase": _phase_now(summary.get("phases") or [], today),
            "goal_status": goal.status if goal else "",
            "note": "只和自己的过去比。",
            "label": "模拟",
        }
