"""学习大纲的草稿、确认和当天撤销；不修改其他学习线。"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select

from app.data_access.session import SessionLocal
from app.study.common.db import ensure_schema
from app.study.common.models import (AgentAction, Attempt, Chapter, Course, Goal, KbDocument,
                                     KnowledgePoint, MaterialPage, Note, PlanDay, PlanTask, Question, StudyFile, _now)
from app.study.plan import scheduler
from app.study.plan import service as plan_service
from .models import GoalOutline
from .outline import generate_outline, split_stages, validate_units

FILENAME = "AI 学习大纲（通用知识，非资料原文）"
SEED_MODELS = (Course, Chapter, StudyFile, KbDocument, Note, KnowledgePoint, Question, MaterialPage)


def _dump(value):
    return json.dumps(value, ensure_ascii=False)


def _row_data(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _owned(session, user_id, outline_id):
    row = session.scalar(select(GoalOutline).where(GoalOutline.id == outline_id, GoalOutline.user_id == user_id).with_for_update())
    if row is None:
        raise HTTPException(404, "没有找到这份大纲")
    return row


def _action(session, user_id, outline_id):
    row = session.scalar(select(AgentAction).where(AgentAction.id == f"v2-outline-action-{outline_id}", AgentAction.user_id == user_id))
    if row is None:
        raise HTTPException(409, "大纲上下文不可用，请重新生成")
    return row


def view(row):
    return {"id": row.id, "title": row.title, "status": row.status, "units": json.loads(row.units_json),
            "stages": json.loads(row.stages_json), "label": row.label, "mock": row.label == "模拟"}


def current(user_id):
    """当前目标已确认的大纲；没有则返回 None。只读本人的数据。"""
    from .lecture import current_outline_id
    outline_id = current_outline_id(user_id)
    if not outline_id:
        return None
    with SessionLocal() as session:
        row = session.scalar(select(GoalOutline).where(GoalOutline.id == outline_id, GoalOutline.user_id == user_id))
        if row is None or row.status != "accepted":
            return None
        goal = session.scalar(select(Goal).where(Goal.user_id == user_id))
        learned = json.loads(goal.summary_json or "{}").get("learned_up_to") if goal else 0
        learned = learned if isinstance(learned, int) else 0
        return {**view(row), "learned_up_to": learned, "checkpoints": _checkpoints(session, user_id, row, learned)}


def _checkpoints(session, user_id, row, learned):
    """V2.2 路径图的关卡：每个阶段末尾一个。已考给分数；该阶段都学完了就是可以考。"""
    from .models import Assessment
    scores = {}
    for record in session.scalars(select(Assessment).where(
            Assessment.user_id == user_id, Assessment.outline_id == row.id,
            Assessment.stage_no > 0, Assessment.status == "submitted")):
        scores[record.stage_no] = record.score
    out = []
    for stage in json.loads(row.stages_json):
        no = stage["no"]
        if no in scores:
            status = "done"
        elif stage["unit_nos"] and max(stage["unit_nos"]) <= learned:
            status = "ready"
        else:
            status = "upcoming"
        out.append({"stage_no": no, "after_unit": max(stage["unit_nos"]) if stage["unit_nos"] else 0,
                    "title": stage.get("title", ""), "status": status, "score": scores.get(no)})
    return out


def advance(user_id, unit_no):
    """V2.1「学下一讲」：今天三件之外多学的一讲也算进度。只能往后推一讲，重复提交不变。"""
    with SessionLocal.begin() as session:
        goal = session.scalar(select(Goal).where(Goal.user_id == user_id).with_for_update())
        outline_id = json.loads(goal.summary_json or "{}").get("v2", {}).get("outline_id") if goal else ""
        row = session.scalar(select(GoalOutline).where(GoalOutline.id == outline_id, GoalOutline.user_id == user_id)) if outline_id else None
        if row is None or row.status != "accepted":
            raise HTTPException(409, "还没有确认大纲")
        summary = json.loads(goal.summary_json or "{}")
        learned = summary.get("learned_up_to") if isinstance(summary.get("learned_up_to"), int) else 0
        if unit_no > len(json.loads(row.units_json)) or unit_no > learned + 1:
            raise HTTPException(422, "只能接着学下一讲")
        if unit_no == learned + 1:
            summary["learned_up_to"] = unit_no
            goal.summary_json = _dump(summary)
            learned = unit_no
        return {"learned_up_to": learned}


def draft(user_id, goal):
    ensure_schema()
    goal = {**goal, "today": plan_service.today_for(user_id).isoformat()}
    units, mocked = generate_outline(user_id, goal)
    outline_id = uuid.uuid4().hex
    with SessionLocal() as session:
        row = GoalOutline(id=outline_id, user_id=user_id, goal_type=goal["goal_type"], title=goal["title"],
                          units_json=_dump(units), stages_json=_dump(split_stages(len(units))),
                          label="模拟" if mocked else "AI 整理，可以改")
        session.add(row)
        session.add(AgentAction(id=f"v2-outline-action-{outline_id}", user_id=user_id,
                                trigger="v2.outline", suggestion_json=_dump({"goal": goal})))
        session.commit()
        return view(row)


def patch(user_id, outline_id, units):
    normalized = validate_units(units)
    with SessionLocal() as session:
        row = _owned(session, user_id, outline_id)
        if row.status != "draft":
            raise HTTPException(409, "只有草稿可以修改")
        row.units_json, row.stages_json = _dump(normalized), _dump(split_stages(len(normalized)))
        row.updated_at = _now()
        session.commit()
        return view(row)


def _clean_seed(session, user_id):
    """仅删除本用户 seed 前缀行；作答及其题目永远保留。快照供撤销恢复。"""
    attempted = set(session.scalars(select(Attempt.question_id).where(Attempt.user_id == user_id)))
    snapshots = {}
    for model in SEED_MODELS:
        rows = list(session.scalars(select(model).where(model.user_id == user_id, model.id.startswith(user_id + ":", autoescape=True))))
        snapshots[model.__tablename__] = []
        for row in rows:
            if model is Question and row.id in attempted:
                continue
            snapshots[model.__tablename__].append(_row_data(row))
            session.delete(row)
    session.flush()
    return snapshots


def _write_materials(session, user_id, row, goal_id, units):
    prefix = f"v2-outline-{row.id}"
    # 问答按文件创建时间选择初始讲次，首讲应是这批文件中最新的。
    created_at = datetime.now(timezone.utc)
    session.add(Course(id=prefix, user_id=user_id, goal_id=goal_id, title=row.title, sort_order=1))
    for unit in units:
        number = unit["no"]
        file_id, lecture_id = f"{prefix}-{number}", f"lec-{number}"
        session.add(Chapter(id=f"{prefix}-chapter-{number}", user_id=user_id, course_id=prefix,
                            title=unit["title"], sort_order=number, lecture_id=lecture_id))
        session.add(StudyFile(id=file_id, user_id=user_id, filename=FILENAME,
                              storage_path=f"v2-outline://{row.id}/{number}", parse_status="ready",
                              lecture_id=lecture_id,
                              created_at=(created_at - timedelta(seconds=number - 1)).isoformat()))
        session.add(MaterialPage(id=f"{prefix}-page-{number}", user_id=user_id, lecture_id=lecture_id,
                                 file_id=file_id, page_no=1, text=unit["title"] + "\n" + "\n".join(unit["points"])))


def _replan(session, user_id, plan, outline_id):
    """调用计划线公开的纯排程函数；只替换未完成项，不丢失已完成记录。"""
    tasks = list(session.scalars(select(PlanTask).where(PlanTask.user_id == user_id, PlanTask.plan_day_id == plan.id).order_by(PlanTask.sort_order)))
    keep = [task for task in tasks if task.status == "done"]
    for task in tasks:
        if task.status != "done":
            session.delete(task)
    session.flush()
    inputs = plan_service.gather_inputs(session, user_id, plan_service.today_for(user_id))
    drafts = scheduler.schedule(inputs)
    kept = [(task.kind, {key: value for key, value in json.loads(task.ref_json).items() if key != "since"}) for task in keep]
    for item in drafts:
        if len(keep) >= scheduler.MAX_TASKS:
            break
        if (item.kind, item.ref) in kept:
            continue
        text = scheduler.describe(item.kind, item.ref, plan.intensity)
        task = PlanTask(id=f"v2-outline-{outline_id}-task-{uuid.uuid4().hex}", user_id=user_id,
                        plan_day_id=plan.id, day=plan.day, kind=item.kind, title=text["title"],
                        ref_json=_dump({**item.ref, "since": _now()}), done_when=text["done_when"], sort_order=len(keep) + 1)
        session.add(task)
        keep.append(task)


def accept(user_id, outline_id):
    # 先确认归属，不因他人的 id 创建本用户的计划或样例。
    with SessionLocal() as session:
        _owned(session, user_id, outline_id)
    plan_id = plan_service.ensure_today_plan(user_id)
    today = plan_service.today_for(user_id).isoformat()
    with SessionLocal() as session:
        row = _owned(session, user_id, outline_id)
        if row.status == "accepted":
            result = view(row)  # 重复点击不写第二套资料。
        elif row.status != "draft":
            raise HTTPException(409, "这份大纲已经处理过了")
        else:
            action = _action(session, user_id, outline_id)
            context = json.loads(action.suggestion_json)["goal"]
            goal = session.scalar(select(Goal).where(Goal.user_id == user_id))
            plan = session.get(PlanDay, plan_id)
            previous = json.loads(goal.summary_json).get("v2", {})
            if previous.get("outline_id") and previous["outline_id"] != outline_id:
                raise HTTPException(409, "请先撤销当前大纲，再确认另一份")
            snapshot = {"goal": _row_data(goal), "intensity": plan.intensity,
                        "tasks": [_row_data(task) for task in session.scalars(select(PlanTask).where(PlanTask.user_id == user_id, PlanTask.plan_day_id == plan.id))],
                        "day": today, "seed": _clean_seed(session, user_id)}
            units = json.loads(row.units_json)
            _write_materials(session, user_id, row, goal.id, units)
            goal.title, goal.exam_date, goal.lecture_count = row.title, context.get("deadline") or "", len(units)
            goal.daily_minutes, goal.status = context["daily_minutes"], "active"
            intensity = "light" if goal.daily_minutes <= 20 else "normal" if goal.daily_minutes <= 40 else "sprint"
            goal.summary_json = _dump({"confirmed": True, "learned_up_to": 0, "default_intensity": intensity,
                                       "v2": {"outline_id": row.id, "materials": "none"}})
            plan.intensity = intensity
            row.goal_id, row.status, row.updated_at = goal.id, "accepted", _now()
            stages = json.loads(row.stages_json)
            stages[0]["started_at"] = today
            row.stages_json = _dump(stages)
            action.before_json, action.after_json, action.status = _dump(snapshot), _dump({"day": today}), "executed"
            session.flush()
            _replan(session, user_id, plan, row.id)
            session.commit()
            result = view(row)
    return {"outline": result, "plan_today": plan_service.plan_today(user_id)}


def undo(user_id, outline_id):
    today = plan_service.today_for(user_id).isoformat()
    with SessionLocal() as session:
        row = _owned(session, user_id, outline_id)
        action = _action(session, user_id, outline_id)
        if row.status != "accepted" or action.status != "executed":
            raise HTTPException(409, "这份大纲尚未生效或已撤销")
        snapshot = json.loads(action.before_json)
        if snapshot["day"] != today:
            raise HTTPException(409, "这份大纲仅在确认当天可以撤销")
        goal = session.scalar(select(Goal).where(Goal.user_id == user_id))
        if json.loads(goal.summary_json).get("v2", {}).get("outline_id") != row.id:
            raise HTTPException(409, "目标已有新的变化，请先处理当前目标")
        for key, value in snapshot["goal"].items():
            setattr(goal, key, value)
        prefix = f"v2-outline-{row.id}"
        for model in (MaterialPage, StudyFile, Chapter, Course):
            for item in session.scalars(select(model).where(model.user_id == user_id, (model.id == prefix) | model.id.startswith(prefix + "-", autoescape=True))):
                session.delete(item)
        for model in SEED_MODELS:
            for data in snapshot["seed"][model.__tablename__]:
                if session.get(model, data["id"]) is None:
                    session.add(model(**data))
        plan = session.scalar(select(PlanDay).where(PlanDay.user_id == user_id, PlanDay.day == today))
        plan.intensity = snapshot["intensity"]
        # 恢复原待办，同时保留确认后新完成的记录；不删除任何 attempts。
        for task in list(session.scalars(select(PlanTask).where(PlanTask.user_id == user_id, PlanTask.plan_day_id == plan.id))):
            if task.status != "done":
                session.delete(task)
        session.flush()
        current_ids = set(session.scalars(select(PlanTask.id).where(PlanTask.user_id == user_id, PlanTask.plan_day_id == plan.id)))
        completed = session.scalar(select(PlanTask.id).where(PlanTask.user_id == user_id, PlanTask.plan_day_id == plan.id, PlanTask.status == "done").limit(1))
        for data in snapshot["tasks"]:
            if data["id"] not in current_ids and (not completed or data["status"] == "done"):
                session.add(PlanTask(**data))
        row.status, row.updated_at = "draft", _now()
        row.stages_json = _dump(split_stages(len(json.loads(row.units_json))))
        action.status = "undone"
        session.commit()
    return {"plan_today": plan_service.plan_today(user_id)}
