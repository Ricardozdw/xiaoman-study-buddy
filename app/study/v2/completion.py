"""汇总当前 V2 目标的学习记录，确认和撤销只更新目标。"""
import json
from collections import Counter
from fractions import Fraction
from threading import Lock

from fastapi import HTTPException
from sqlalchemy import select

from app.data_access.session import SessionLocal
from app.study.common.db import ensure_schema
from app.study.common.models import Attempt, Goal, PlanTask, Question
from app.study.dashboard.service import local_day, mapping
from app.study.plan import demo
from app.study.practice.service import meta
from .models import Assessment, GoalOutline

PASS_SCORE = 70
_write_lock = Lock()  # SQLite 不支持行锁，串行处理本机的确认和撤销。


def _goal_outline(session, user_id, *, lock=False):
    query = select(Goal).where(Goal.user_id == user_id)
    goal = session.scalar(query.with_for_update() if lock else query)
    summary = mapping(goal.summary_json) if goal else {}
    v2 = summary.get("v2", {})
    outline = session.scalar(select(GoalOutline).where(
        GoalOutline.user_id == user_id, GoalOutline.goal_id == goal.id,
        GoalOutline.id == v2.get("outline_id"), GoalOutline.status == "accepted",
    )) if goal and v2.get("outline_id") else None
    return goal, outline, summary


def _completed_tasks(session, user_id, started_at):
    tasks = session.scalars(select(PlanTask).where(
        PlanTask.user_id == user_id, PlanTask.status == "done",
    ))
    days, learned = set(), set()
    for task in tasks:
        ref = mapping(task.ref_json)
        # 计划任务的 since 是排程时间，能区分重新确认大纲前的同名讲次。
        if (ref.get("since") or "") < started_at:
            continue
        days.add(task.day)
        if task.kind == "learn":
            learned.update(ref.get("lecture_nos") or [ref.get("lecture_no")])
    return days, learned


def _card(session, outline):
    user_id, started_at = outline.user_id, outline.updated_at
    units = json.loads(outline.units_json)
    days, learned = _completed_tasks(session, user_id, started_at)
    attempts = session.execute(
        select(Attempt, Question)
        .outerjoin(Question, (Question.id == Attempt.question_id) & (Question.user_id == user_id))
        .where(Attempt.user_id == user_id, Attempt.created_at >= started_at)
    ).all()
    total, correct = Counter(), Counter()
    mock = False
    for attempt, question in attempts:
        day = local_day(attempt.created_at)
        if day:
            days.add(day.isoformat())
        if question:
            total[question.lecture_id] += 1
            correct[question.lecture_id] += bool(attempt.correct)
            mock = mock or bool(meta(question).get("mock", True))

    rates = {}
    for unit in units:
        lecture = f"lec-{unit['no']}"
        if total[lecture]:
            rates[unit["title"]] = Fraction(correct[lecture], total[lecture])
    reports = list(session.scalars(select(Assessment).where(
        Assessment.user_id == user_id, Assessment.outline_id == outline.id,
        Assessment.created_at >= started_at, Assessment.status == "submitted",
        Assessment.score.is_not(None),
    ).order_by(Assessment.submitted_at, Assessment.id)))
    mock = mock or any(mapping(report.report_json).get("mock") for report in reports)
    card = {
        "days": len(days), "attempts": len(attempts),
        "first_score": reports[0].score if reports else None,
        "last_score": reports[-1].score if reports else None,
        # 有作答的单元全部答对时，不标“最难的单元”。
        "hardest_unit": None if not rates or all(rate == 1 for rate in rates.values()) else min(rates, key=rates.get),
        "label": "模拟" if mock else "",
    }
    eligible = (card["last_score"] is not None and card["last_score"] >= PASS_SCORE
                and all(unit["no"] in learned for unit in units))
    return card, eligible


def status(user_id):
    ensure_schema()
    with SessionLocal() as session:
        goal, outline, _ = _goal_outline(session, user_id)
        if outline is None:
            return {"suggest": False, "reason": None, "card": None, "done": False}
        card, eligible = _card(session, outline)
        done = goal.status == "done"
        suggest = eligible and not done
        return {"suggest": suggest, "reason": "all_done" if suggest else None, "card": card, "done": done}


def confirm(user_id, reason):
    ensure_schema()
    with _write_lock, SessionLocal.begin() as session:
        goal, outline, summary = _goal_outline(session, user_id, lock=True)
        if outline is None:
            raise HTTPException(404, "还没有确认学习大纲")
        card, eligible = _card(session, outline)
        if goal.status == "done":
            return card
        if reason == "suggested" and not eligible:
            raise HTTPException(409, "当前目标还没有达到建议收尾的条件")
        goal.status = "done"
        summary["v2"]["completed_at"] = demo.today(user_id).isoformat()
        goal.summary_json = json.dumps(summary, ensure_ascii=False)
        return card


def undo(user_id):
    ensure_schema()
    with _write_lock, SessionLocal.begin() as session:
        goal, outline, summary = _goal_outline(session, user_id, lock=True)
        if outline is None:
            raise HTTPException(404, "还没有确认学习大纲")
        if goal.status != "done" or summary["v2"].get("completed_at") != demo.today(user_id).isoformat():
            raise HTTPException(409, "目标完成仅可在确认当天撤销")
        goal.status = "active"
        del summary["v2"]["completed_at"]
        goal.summary_json = json.dumps(summary, ensure_ascii=False)
    return {"done": False}
