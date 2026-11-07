"""阶段测验复用练习线的出题和作答，阶段与报告只写 V2 表。"""
from __future__ import annotations

import json
from datetime import date
from threading import RLock
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from sqlalchemy import select

from app.data_access.session import SessionLocal
from app.study.common.db import ensure_schema
from app.study.common.models import PlanTask, Question, _now
from app.study.plan import demo, service as plan_service
from app.study.practice import service as practice_service
from app.study.practice.capabilities import PracticeError
from app.study.practice.schemas import AttemptBody, QuizBody

from .models import Assessment, GoalOutline

QUESTION_COUNT = 10
_locks = [RLock() for _ in range(64)]


def _lock(user_id):
    # SQLite 的行查询不加行锁，本机写入按用户串行。Postgres 另用大纲行锁。
    return _locks[hash(user_id) % len(_locks)]


def _outline(session, user_id, *, lock=False):
    query = select(GoalOutline).where(GoalOutline.user_id == user_id, GoalOutline.status == "accepted")
    return session.scalar(query.with_for_update() if lock else query)


def _id(outline, stage_no):
    # 撤销并重新确认的大纲有新的 updated_at，避免复用旧一轮的测验。
    return uuid5(NAMESPACE_URL, f"xiaoman:assessment:{outline.id}:{outline.updated_at}:{stage_no}").hex


def _stage_view(stage):
    return {key: stage[key] for key in ("no", "title", "unit_nos")}


def _reason(session, user_id, outline, stage, today):
    refs = session.scalars(select(PlanTask.ref_json).where(
        PlanTask.user_id == user_id, PlanTask.kind == "learn", PlanTask.status == "done",
    ))
    learned = set()
    for ref_json in refs:
        ref = json.loads(ref_json)
        if ref.get("since") and ref["since"] < outline.updated_at:
            continue
        # 计划线也会排一项学两讲的任务，勾选后两讲都计入。
        learned.update(ref.get("lecture_nos") or [ref.get("lecture_no")])
    if set(stage["unit_nos"]).issubset(learned):
        return "stage_done"
    if stage.get("started_at") and (today - date.fromisoformat(stage["started_at"])).days >= 7:
        return "seven_days"
    return None


def _current(session, user_id, outline):
    if outline is None:
        return None, None, None
    for stage in json.loads(outline.stages_json):
        record = session.scalar(select(Assessment).where(
            Assessment.id == _id(outline, stage["no"]), Assessment.user_id == user_id,
        ))
        if record is not None and record.status == "submitted":
            continue
        reason = (json.loads(record.report_json)["reason"] if record is not None
                  else _reason(session, user_id, outline, stage, demo.today(user_id)))
        return stage, record, reason
    return None, None, None


def due(user_id):
    ensure_schema()
    with SessionLocal() as session:
        stage, record, reason = _current(session, user_id, _outline(session, user_id))
        return {"due": reason is not None, "stage": _stage_view(stage) if stage else None,
                "reason": reason, "open_id": record.id if record else None}


def _questions(session, user_id, ids):
    rows = session.scalars(select(Question).where(Question.user_id == user_id, Question.id.in_(ids))).all()
    questions = {row.id: row for row in rows}
    if len(questions) != len(ids):
        raise HTTPException(409, "测验题目暂时不可用")
    return [questions[qid] for qid in ids]


def _view(session, user_id, stage, record):
    ids = json.loads(record.question_ids_json)
    questions = _questions(session, user_id, ids)
    mock = json.loads(record.report_json)["mock"]
    return {"id": record.id, "stage": _stage_view(stage), "mock": mock,
            "label": "模拟" if mock else "AI 整理，可以改",
            "questions": [{"id": q.id, "stem": q.stem, "options": json.loads(q.options_json)} for q in questions]}


def start(user_id):
    ensure_schema()
    with _lock(user_id), SessionLocal.begin() as session:
        outline = _outline(session, user_id, lock=True)
        stage, record, reason = _current(session, user_id, outline)
        if reason is None:
            raise HTTPException(409, "这一阶段还没有到测验时间")
        if record is not None:
            return _view(session, user_id, stage, record)

        unit_nos = stage["unit_nos"]
        count, extra = divmod(QUESTION_COUNT, len(unit_nos))
        quiz_ids = {}
        mock = False
        for index, number in enumerate(unit_nos):
            size = count + (index < extra)
            try:
                quiz = practice_service.create_quiz(user_id, QuizBody(lecture_id=f"lec-{number}", count=size, difficulty="easy"))
            except PracticeError as exc:
                raise HTTPException(422, str(exc)) from None
            if len(quiz["questions"]) != size:
                raise HTTPException(409, "这次通过检查的题目还不够 10 道，请稍后重试")
            quiz_ids.update((question["id"], quiz["quiz_id"]) for question in quiz["questions"])
            mock = mock or quiz["mock"]
        if len(quiz_ids) != QUESTION_COUNT:
            raise HTTPException(409, "这次通过检查的题目还不够 10 道，请稍后重试")

        record = Assessment(id=_id(outline, stage["no"]), user_id=user_id, outline_id=outline.id,
                            stage_no=stage["no"], status="open", question_ids_json=json.dumps(list(quiz_ids)),
                            report_json=json.dumps({"quiz_ids": quiz_ids, "mock": mock, "reason": reason}))
        session.add(record)
        return _view(session, user_id, stage, record)


def _record(session, user_id, assessment_id):
    record = session.scalar(select(Assessment).where(Assessment.id == assessment_id, Assessment.user_id == user_id))
    if record is None:
        raise HTTPException(404, "没有找到这次阶段测验")
    return record


def _check_outline(outline, record):
    if outline is None or outline.id != record.outline_id or _id(outline, record.stage_no) != record.id:
        raise HTTPException(409, "这份学习大纲已经变化，请返回当前计划")


def _pending_practice(plan):
    return [task["id"] for task in plan["tasks"] if task["kind"] == "practice" and task["status"] == "todo"]


def _prepare_submission(user_id, assessment_id, answers):
    with SessionLocal.begin() as session:
        outline = _outline(session, user_id, lock=True)
        record = _record(session, user_id, assessment_id)
        state = json.loads(record.report_json)
        if record.status == "submitted" or "submission" in state:
            return
        _check_outline(outline, record)
        if not answers:
            raise HTTPException(422, "先回答至少一道题，就可以交卷")
        if not answers.keys() <= state["quiz_ids"].keys():
            raise HTTPException(422, "提交的题目不属于这次测验")
        for question in _questions(session, user_id, list(answers)):
            if answers[question.id] not in {option["id"] for option in json.loads(question.options_json)}:
                raise HTTPException(422, "请选择题目中提供的选项")
        before = plan_service.plan_today(user_id)
        # 练习线逐题提交。先保存答案与计划快照，故障后重试可继续同一份交卷。
        state["submission"] = {"answers": answers, "date": before["date"], "pending_practice": _pending_practice(before)}
        record.report_json = json.dumps(state, ensure_ascii=False)


def _complete_practice(user_id, submission):
    plan = plan_service.plan_today(user_id)
    practice = [task for task in plan["tasks"] if task["kind"] == "practice"]
    ids = {task["id"] for task in practice}
    if ids.intersection(plan["auto_completed"]):
        return
    if plan["date"] == submission["date"]:
        before = set(submission["pending_practice"])
        # 另一次计划读取可能已触发自动勾选。用前后状态也能识别这次完成。
        if any(task["id"] in before and task["status"] == "done" for task in practice):
            return
    task_id = next(iter(_pending_practice(plan)), None)
    if task_id is not None:
        plan_service.patch_task(user_id, task_id, status="done")


def _report_units(outline, record):
    stages = json.loads(outline.stages_json)
    stage = stages[record.stage_no - 1]
    next_stage = stages[record.stage_no] if record.stage_no < len(stages) else None
    titles = {unit["no"]: unit["title"] for unit in json.loads(outline.units_json)}
    units = [{"no": no, "title": titles[no], "correct": 0, "total": 0} for no in stage["unit_nos"]]
    by_lecture = {f"lec-{unit['no']}": unit for unit in units}
    return stages, next_stage, units, by_lecture


def submit(user_id, assessment_id, answers):
    ensure_schema()
    with _lock(user_id):
        _prepare_submission(user_id, assessment_id, answers)
        with SessionLocal.begin() as session:
            outline = _outline(session, user_id, lock=True)
            record = _record(session, user_id, assessment_id)
            state = json.loads(record.report_json)
            if record.status == "submitted":
                return state["report"], state["mock"]
            _check_outline(outline, record)
            submission = state["submission"]
            stages, next_stage, units, by_lecture = _report_units(outline, record)
            for question in _questions(session, user_id, list(submission["answers"])):
                result = practice_service.submit(user_id, AttemptBody(
                    question_id=question.id, answer=submission["answers"][question.id], quiz_id=state["quiz_ids"][question.id],
                ))
                unit = by_lecture[question.lecture_id]
                unit["total"] += 1
                unit["correct"] += int(result["correct"])
            answered = sum(unit["total"] for unit in units)
            correct = sum(unit["correct"] for unit in units)
            weak = [unit["no"] for unit in units if unit["total"] and unit["correct"] * 5 < unit["total"] * 3]
            score = round(100 * correct / answered)
            summary = f"这一阶段做了 {answered} 题，对了 {correct} 题。"
            if weak:
                summary += f"第 {'、'.join(map(str, weak))} 单元再看一眼会更稳。"
            report = {"score": score, "units": units, "weak_unit_nos": weak,
                      "next_stage": _stage_view(next_stage) if next_stage else None, "summary": summary}
            _complete_practice(user_id, submission)
            if next_stage is not None:
                next_stage["started_at"] = demo.today(user_id).isoformat()
                outline.stages_json = json.dumps(stages, ensure_ascii=False)
            record.status, record.score, record.submitted_at = "submitted", score, _now()
            record.report_json = json.dumps({"report": report, "mock": state["mock"]}, ensure_ascii=False)
            return report, state["mock"]
