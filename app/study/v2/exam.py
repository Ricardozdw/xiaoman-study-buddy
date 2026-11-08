"""V2.1 每天的「考试」（固定第 3 件）。

- 题 = 之前做错的题（优先）+ 当天这一讲的新题，题量按强度 3 / 5 / 8。
- 学完一个阶段的那天，考试就是阶段测验（10 题、成绩报告），不另出一场。
- 交卷只勾掉「考试」这一件；作答不会顺带把「练一练」自动勾掉（计划线排除了考试题）。
记录复用 assessments 表，stage_no = 0 表示每日考试，阶段测验仍是 1、2、3…
"""
from __future__ import annotations

import json
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from sqlalchemy import select

from app.data_access.session import SessionLocal
from app.study.common.db import ensure_schema
from app.study.common.models import Question, _now
from app.study.plan import scheduler, service as plan_service
from app.study.practice import service as practice_service
from app.study.practice.capabilities import PracticeError
from app.study.practice.schemas import AttemptBody, QuizBody

from . import assessment
from .models import Assessment

DAILY_STAGE_NO = 0


def _exam_task(user_id):
    plan = plan_service.plan_today(user_id)
    task = next((item for item in plan["tasks"] if item["kind"] == "exam"), None)
    if task is None:
        raise HTTPException(409, "今天没有排考试")
    return plan, task


def _id(task_id):
    return uuid5(NAMESPACE_URL, f"xiaoman:daily-exam:{task_id}").hex


def _view(session, user_id, record):
    state = json.loads(record.report_json)
    ids = json.loads(record.question_ids_json)
    rows = {row.id: row for row in session.scalars(select(Question).where(Question.user_id == user_id, Question.id.in_(ids)))}
    if len(rows) != len(ids):
        raise HTTPException(409, "考试题目暂时不可用")
    return {
        "type": "daily", "id": record.id, "mock": state["mock"], "label": "模拟" if state["mock"] else "AI 整理，可以改",
        "lecture_no": state["lecture_no"], "mistake_count": state["mistake_count"],
        "submitted": record.status == "submitted", "report": state.get("report"),
        "questions": [{"id": rows[qid].id, "stem": rows[qid].stem, "options": json.loads(rows[qid].options_json)} for qid in ids],
    }


def start(user_id):
    """开考。阶段到点时转为阶段测验；同一天重复点返回同一份卷子。"""
    ensure_schema()
    plan, task = _exam_task(user_id)
    if assessment.due(user_id)["due"]:
        return {"type": "stage", **assessment.start(user_id)}
    record_id = _id(task["id"])
    with assessment._lock(user_id), SessionLocal.begin() as session:
        record = session.scalar(select(Assessment).where(Assessment.id == record_id, Assessment.user_id == user_id))
        if record is not None:
            return _view(session, user_id, record)
        outline = assessment._outline(session, user_id)
        if outline is None:
            raise HTTPException(409, "还没有确认大纲")
        ref = task["ref"]
        count = scheduler.EXAM_COUNT.get(plan["intensity"], scheduler.EXAM_COUNT["normal"])
        wanted = list(ref.get("mistake_ids") or [])
        existing = set(session.scalars(select(Question.id).where(Question.user_id == user_id, Question.id.in_(wanted))))
        mistakes = [qid for qid in wanted if qid in existing][:count]
        quiz_ids = {qid: "" for qid in mistakes}
        mock = False
        rest = count - len(mistakes)
        if rest > 0:
            try:
                # 考试用中等难度：和“练一练”（easy）分开出题，否则题数相同时会原样复用练习题，
                # 既等于考原题，也会让当日总结把练习作答算成考试题。
                quiz = practice_service.create_quiz(user_id, QuizBody(lecture_id=ref["lecture_id"], count=rest, difficulty="medium"))
            except PracticeError as exc:
                raise HTTPException(422, str(exc)) from None
            for question in quiz["questions"]:
                quiz_ids.setdefault(question["id"], quiz["quiz_id"])
            mock = bool(quiz["mock"])
        if not quiz_ids:
            raise HTTPException(409, "这次没能出好题，请稍后再试")
        record = Assessment(
            id=record_id, user_id=user_id, outline_id=outline.id, stage_no=DAILY_STAGE_NO, status="open",
            question_ids_json=json.dumps(list(quiz_ids)),
            report_json=json.dumps({"kind": "daily", "task_id": task["id"], "quiz_ids": quiz_ids, "mock": mock,
                                    "lecture_no": ref.get("lecture_no"), "mistake_count": len(mistakes)}, ensure_ascii=False),
        )
        session.add(record)
        session.flush()
        return _view(session, user_id, record)


def submit(user_id, exam_id, answers):
    """交卷：逐题判分，写成绩，只勾掉考试这一件。重复交卷返回第一次的成绩。"""
    ensure_schema()
    with assessment._lock(user_id):
        with SessionLocal.begin() as session:
            record = session.scalar(select(Assessment).where(Assessment.id == exam_id, Assessment.user_id == user_id,
                                                            Assessment.stage_no == DAILY_STAGE_NO))
            if record is None:
                raise HTTPException(404, "没有找到这次考试")
            state = json.loads(record.report_json)
            if record.status == "submitted":
                return state["report"], state["mock"]
            if not answers:
                raise HTTPException(422, "先回答至少一道题，就可以交卷")
            if not answers.keys() <= state["quiz_ids"].keys():
                raise HTTPException(422, "提交的题目不属于这次考试")
            rows = {row.id: row for row in session.scalars(select(Question).where(Question.user_id == user_id, Question.id.in_(list(answers))))}
            for qid, answer in answers.items():
                if qid not in rows or answer not in {option["id"] for option in json.loads(rows[qid].options_json)}:
                    raise HTTPException(422, "请选择题目中提供的选项")
        correct = 0
        wrong_old = 0
        mistakes = set(list(state["quiz_ids"])[: state["mistake_count"]])
        for qid, answer in answers.items():
            result = practice_service.submit(user_id, AttemptBody(question_id=qid, answer=answer, quiz_id=state["quiz_ids"][qid]))
            correct += int(result["correct"])
            wrong_old += int(qid in mistakes and not result["correct"])
        total = len(answers)
        score = round(100 * correct / total)
        summary = f"这次做了 {total} 题，对了 {correct} 题。"
        if state["mistake_count"]:
            fixed = state["mistake_count"] - wrong_old
            summary += f"之前错的 {state['mistake_count']} 题，这次做对了 {max(fixed, 0)} 题。"
        report = {"score": score, "correct": correct, "total": total, "summary": summary}
        task_id = state["task_id"]
        with SessionLocal.begin() as session:
            record = session.scalar(select(Assessment).where(Assessment.id == exam_id, Assessment.user_id == user_id))
            record.status, record.score, record.submitted_at = "submitted", score, _now()
            record.report_json = json.dumps({**state, "report": report}, ensure_ascii=False)
        plan_service.patch_task(user_id, task_id, status="done")
        return report, state["mock"]


def exam_question_ids(session, user_id) -> set[str]:
    """考试和阶段测验用过的题；计划线据此不把它们算进「练一练」。"""
    ids: set[str] = set()
    for raw in session.scalars(select(Assessment.question_ids_json).where(Assessment.user_id == user_id)):
        ids.update(json.loads(raw or "[]"))
    return ids
