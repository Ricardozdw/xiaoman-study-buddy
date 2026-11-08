"""V2.2 今天完成 + 当日总结。只读计划、作答、考试记录；不调模型，文案用模板。

- 不提「连续」、不比较他人；累计天数 = 有任意一件完成的日子数，断了不清零。
- 「今天」以计划线为准（含演示开关）；作答按今天任务排进来之后（ref.since）统计。
"""
from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import select

from app.data_access.session import SessionLocal
from app.study.common.db import ensure_schema
from app.study.common.models import Attempt, Goal, PlanDay, PlanTask
from app.study.plan import service as plan_service

from . import exam as exam_module
from .models import Assessment, GoalOutline


def today(user_id: str) -> dict:
    ensure_schema()
    plan = plan_service.plan_today(user_id)
    day = plan_service.today_for(user_id)
    tasks = plan["tasks"]
    with SessionLocal() as session:
        goal = session.scalar(select(Goal).where(Goal.user_id == user_id))
        summary = json.loads(goal.summary_json or "{}") if goal else {}
        outline_id = summary.get("v2", {}).get("outline_id", "")
        outline = session.scalar(select(GoalOutline).where(GoalOutline.id == outline_id, GoalOutline.user_id == user_id)) if outline_id else None
        titles = {unit.get("no", index + 1): unit["title"] for index, unit in enumerate(json.loads(outline.units_json))} if outline else {}

        learned = [task["ref"].get("lecture_no") for task in tasks if task["kind"] == "learn" and task["status"] == "done"]
        extra = summary.get("v2_extra") if isinstance(summary.get("v2_extra"), dict) else {}
        if extra.get("day") == day.isoformat():
            learned += [no for no in extra.get("nos", []) if no not in learned]
        lectures = [{"no": no, "title": titles.get(no, "")} for no in learned if isinstance(no, int)]

        # 练一练：今天任务排进来之后、非考试题的作答。
        since = min((str(task["ref"].get("since") or "") for task in tasks if task["ref"].get("since")), default="")
        exam_ids = exam_module.exam_question_ids(session, user_id)
        attempts = [row for row in session.scalars(select(Attempt).where(Attempt.user_id == user_id))
                    if since and (row.created_at or "") >= since and row.question_id not in exam_ids]
        practice = {"total": len(attempts), "correct": sum(1 for row in attempts if row.correct)}

        # 考试：今天的每日考试，或今天交卷的阶段测验。
        exam = None
        exam_task = next((task for task in tasks if task["kind"] == "exam"), None)
        if exam_task is not None:
            record = session.scalar(select(Assessment).where(Assessment.id == exam_module._id(exam_task["id"]), Assessment.user_id == user_id))
            if record is not None and record.status == "submitted":
                state = json.loads(record.report_json)
                report = state.get("report", {})
                exam = {"kind": "daily", "score": record.score, "total": report.get("total", 0), "correct": report.get("correct", 0),
                        "mistakes": state.get("mistake_count", 0)}
        if exam is None and since:
            stage = session.scalar(select(Assessment).where(
                Assessment.user_id == user_id, Assessment.stage_no > 0, Assessment.status == "submitted",
                Assessment.submitted_at >= since).order_by(Assessment.submitted_at.desc()))
            if stage is not None:
                exam = {"kind": "stage", "score": stage.score, "stage_no": stage.stage_no}

        # 累计天数：有任意一件完成的日子；本周 = 计划线「今天」所在的周一到周日。
        done_days = set(session.scalars(
            select(PlanDay.day).join(PlanTask, PlanTask.plan_day_id == PlanDay.id)
            .where(PlanDay.user_id == user_id, PlanTask.user_id == user_id, PlanTask.status == "done")))
    monday = day - timedelta(days=day.weekday())
    week = {(monday + timedelta(days=offset)).isoformat() for offset in range(7)}
    all_done = bool(tasks) and all(task["status"] == "done" for task in tasks)
    return {
        "all_done": all_done,
        "lectures": lectures,
        "practice": practice,
        "exam": exam,
        "minutes": plan.get("minutes", 0),
        "total_days": len(done_days),
        "week_days": len(done_days & week),
        "lines": _lines(lectures, practice, exam, len(done_days), len(done_days & week)),
    }


def _lines(lectures, practice, exam, total_days, week_days):
    lines = []
    if lectures:
        lines.append("今天学了：" + "、".join(f"第 {item['no']} 讲「{item['title']}」" if item["title"] else f"第 {item['no']} 讲" for item in lectures))
    if practice["total"]:
        lines.append(f"练一练：做了 {practice['total']} 题，对了 {practice['correct']} 题")
    if exam and exam["kind"] == "daily":
        line = f"考试：{exam['score']} 分"
        if exam.get("mistakes"):
            line += f"（含 {exam['mistakes']} 道之前的错题）"
        lines.append(line)
    elif exam:
        lines.append(f"阶段 {exam['stage_no']} 测验：{exam['score']} 分")
    lines.append(f"累计学了 {total_days} 天，本周 {week_days} 天")
    return lines
