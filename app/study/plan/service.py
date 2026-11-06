"""计划线：读学习记录 → 交给排程规则 → 存成当天计划。

- 当天第一次打开时算一次，存进 plan_days / plan_tasks；同一天再打开不重新洗牌。
- 没做完的任务不搬到新的一天；新的一天重新算，仍最多三件。
- 新的一天强度回到“正常”（强度只算今天）。
- 勾完“学新的”，已学到第几讲 +1，明天自然排下一讲。
- 错题、掌握度、资料状态只读练习线和资料线的表，不改它们。
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.data_access.session import SessionLocal
from app.study.common import store
from app.study.common.models import (
    AgentAction,
    Attempt,
    Chapter,
    Goal,
    KnowledgePoint,
    PlanDay,
    PlanTask,
    Question,
    StudyFile,
)
from app.study.plan import daily, demo, returning, scheduler
from app.study.plan.scheduler import (
    KIND_LABEL,
    LectureState,
    MistakeItem,
    PlanInputs,
    ReviewItem,
)

_TZ = ZoneInfo("Asia/Shanghai")
INTENSITY = store.INTENSITY  # light / normal / sprint → (中文, 分钟)
DEFAULT_INTENSITY = "normal"


# ---------- 日期 ----------


def today_for(user_id: str) -> date:
    """计划线眼里的“今天”：真实今天 + 演示开关往后跳的天数（开关关着时为 0）。"""
    return demo.today(user_id)


def _local_date(raw: str) -> Optional[date]:
    """把库里的时间（UTC ISO 或 YYYY-MM-DD）换成上海日期。"""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        if len(text) == 10:
            return date.fromisoformat(text)
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        return moment.date()
    return moment.astimezone(_TZ).date()


def _loads(raw: str, default: Any) -> Any:
    try:
        value = json.loads(raw or "")
    except json.JSONDecodeError:
        return default
    return value if isinstance(value, type(default)) else default


# ---------- 读学习记录 ----------


def _lectures(session, user_id: str, lecture_count: int) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for chapter in session.scalars(select(Chapter).where(Chapter.user_id == user_id)).all():
        number = scheduler.lecture_no_for(chapter.lecture_id) or chapter.sort_order
        if number and number > 0:
            out[number] = {
                "lecture_id": chapter.lecture_id or scheduler.lecture_id_for(number),
                "title": chapter.title or f"第 {number} 讲",
                "has_material": False,
            }
    ready = session.scalars(
        select(StudyFile.lecture_id).where(StudyFile.user_id == user_id, StudyFile.parse_status == "ready")
    ).all()
    for lecture_id in ready:
        number = scheduler.lecture_no_for(lecture_id)
        if number is None:
            number = next((n for n, item in out.items() if item["lecture_id"] == lecture_id), None)
        if number is None:
            continue
        item = out.setdefault(
            number, {"lecture_id": lecture_id, "title": f"第 {number} 讲", "has_material": False}
        )
        item["has_material"] = True
    for number in range(1, lecture_count + 1):
        out.setdefault(
            number,
            {"lecture_id": scheduler.lecture_id_for(number), "title": f"第 {number} 讲", "has_material": False},
        )
    return out


def _learned_up_to(goal: Goal, lectures: dict[int, dict[str, Any]], lecture_count: int) -> int:
    summary = _loads(goal.summary_json, {})
    value = summary.get("learned_up_to")
    if isinstance(value, int) and value >= 0:
        return min(value, lecture_count)
    # 还没记过：先按“资料已交的最后一讲”算。目标拆解时用户会给出准确值。
    ready = [n for n, item in lectures.items() if item["has_material"]]
    return min(max(ready, default=0), lecture_count)


def gather_inputs(session, user_id: str, today: date) -> PlanInputs:
    goal = session.scalar(select(Goal).where(Goal.user_id == user_id))
    if goal is None:
        return PlanInputs(today=today, goal_active=False, lecture_count=0, learned_up_to=0)

    raw = _lectures(session, user_id, max(goal.lecture_count or 0, 0))
    lecture_count = goal.lecture_count or max(raw, default=0)
    learned = _learned_up_to(goal, raw, lecture_count)

    # 每讲掌握度 = 知识点掌握度平均（练习线写的数，这里只读）。
    points = session.scalars(select(KnowledgePoint).where(KnowledgePoint.user_id == user_id)).all()
    mastery_sum: dict[str, list[int]] = {}
    reviews: list[ReviewItem] = []
    for point in points:
        mastery_sum.setdefault(point.lecture_id, []).append(point.mastery or 0)
        due = _local_date(point.next_review_on)
        if due is not None:
            reviews.append(
                ReviewItem(point.id, point.name, point.lecture_id, point.mastery or 0, due)
            )

    # 作答：每题看最后一次，最后一次答错就还算错题；每讲记最近一次练习的日期。
    questions = {
        row.id: row.lecture_id
        for row in session.scalars(select(Question).where(Question.user_id == user_id)).all()
    }
    attempts = session.scalars(
        select(Attempt).where(Attempt.user_id == user_id).order_by(Attempt.created_at, Attempt.id)
    ).all()
    latest: dict[str, Attempt] = {}
    last_practiced: dict[str, date] = {}
    for attempt in attempts:
        latest[attempt.question_id] = attempt
        lecture_id = questions.get(attempt.question_id)
        when = _local_date(attempt.created_at)
        if lecture_id and when and (lecture_id not in last_practiced or when > last_practiced[lecture_id]):
            last_practiced[lecture_id] = when
    mistakes = []
    for question_id, attempt in latest.items():
        lecture_id = questions.get(question_id)
        when = _local_date(attempt.created_at)
        if not attempt.correct and lecture_id and when:
            mistakes.append(MistakeItem(question_id, lecture_id, when))

    lectures = []
    for number, item in sorted(raw.items()):
        values = mastery_sum.get(item["lecture_id"])
        lectures.append(
            LectureState(
                number=number,
                lecture_id=item["lecture_id"],
                title=item["title"],
                has_material=item["has_material"],
                mastery=round(sum(values) / len(values)) if values else None,
                last_practiced=last_practiced.get(item["lecture_id"]),
            )
        )
    pace = _active_pace(_loads(goal.summary_json, {}), today)
    return PlanInputs(
        today=today,
        goal_active=(goal.status == "active"),
        lecture_count=lecture_count,
        learned_up_to=learned,
        lectures=tuple(lectures),
        mistakes=tuple(mistakes),
        reviews=tuple(reviews),
        learn_per_task=int(pace.get("per_task", 1)) if pace else 1,
        learn_mode=str(pace.get("mode", "")) if pace else "",
    )


def _active_pace(summary: dict[str, Any], today: date) -> Optional[dict[str, Any]]:
    """中断后回来选的补法（一次学两讲），在 until 那天之前（含）有效。"""
    pace = summary.get("pace")
    if not isinstance(pace, dict):
        return None
    until = _local_date(str(pace.get("until") or ""))
    if until is None or until < today:
        return None
    return pace


# ---------- 生成并保存当天计划 ----------


def _is_untouched_seed(user_id: str, tasks: list[PlanTask]) -> bool:
    """地基写死的样例计划，且一件都没勾过。"""
    seed_ids = {f"{user_id}:task-{kind}" for kind in scheduler.KINDS}
    return bool(tasks) and all(t.id in seed_ids for t in tasks) and all(t.status == "todo" for t in tasks)


def _plan_tasks(session, user_id: str, plan_id: str) -> list[PlanTask]:
    return list(
        session.scalars(
            select(PlanTask)
            .where(PlanTask.user_id == user_id, PlanTask.plan_day_id == plan_id)
            .order_by(PlanTask.sort_order)
        ).all()
    )


def _remember_progress(goal: Optional[Goal], learned_up_to: int) -> None:
    if goal is None:
        return
    summary = _loads(goal.summary_json, {})
    if summary.get("learned_up_to") != learned_up_to:
        summary["learned_up_to"] = learned_up_to
        goal.summary_json = json.dumps(summary, ensure_ascii=False)


def _add_drafts(session, user_id: str, plan: PlanDay, drafts, *, keep: list[PlanTask]) -> None:
    """把排程结果写进当天计划。keep 是已完成、要保留的任务；总数不超过三件。"""
    room = scheduler.MAX_TASKS - len(keep)
    kept_refs = [(_row.kind, _loads(_row.ref_json, {})) for _row in keep]
    order = len(keep)
    tag = uuid.uuid4().hex[:6]
    for draft in drafts:
        if room <= 0:
            break
        if (draft.kind, draft.ref) in kept_refs:
            continue
        order += 1
        room -= 1
        text = scheduler.describe(draft.kind, draft.ref, plan.intensity or DEFAULT_INTENSITY)
        session.add(
            PlanTask(
                id=f"{plan.id}:{tag}:t{order}",
                user_id=user_id,
                plan_day_id=plan.id,
                day=plan.day,
                kind=draft.kind,
                title=text["title"],
                ref_json=json.dumps(draft.ref, ensure_ascii=False),
                done_when=text["done_when"],
                status="todo",
                sort_order=order,
            )
        )


def _last_open_before(session, user_id: str, day: str) -> Optional[date]:
    days = session.scalars(
        select(PlanDay.day).where(PlanDay.user_id == user_id, PlanDay.day < day)
    ).all()
    return max((d for d in (_local_date(x) for x in days) if d), default=None)


def _return_context(session, user_id: str, today: date, last_open: Optional[date]) -> returning.ReturnContext:
    inputs = gather_inputs(session, user_id, today)
    goal = session.scalar(select(Goal).where(Goal.user_id == user_id))
    summary = _loads(goal.summary_json, {}) if goal else {}
    floor = summary.get("review_floor")
    return returning.ReturnContext(
        today=today,
        last_open=last_open,
        goal_active=inputs.goal_active,
        exam_date=_local_date(goal.exam_date) if goal else None,
        lecture_count=inputs.lecture_count,
        learned_up_to=inputs.learned_up_to,
        review_floor=floor if isinstance(floor, int) and floor >= 0 else returning.REVIEW_FLOOR_DAYS,
    )


def ensure_today_plan(user_id: str) -> str:
    """返回今天计划的 id；今天还没有就按规则排一份，隔两天以上回来时出一张卡。"""
    store.seed(user_id)
    today = today_for(user_id)
    day = today.isoformat()
    with SessionLocal() as session:
        plan = session.scalar(select(PlanDay).where(PlanDay.user_id == user_id, PlanDay.day == day))
        new_day = plan is None
        if plan is not None:
            existing = _plan_tasks(session, user_id, plan.id)
            if not _is_untouched_seed(user_id, existing):
                return plan.id
            for row in existing:
                session.delete(row)
        else:
            plan = PlanDay(id=f"{user_id}:plan:{day}", user_id=user_id, day=day, intensity=DEFAULT_INTENSITY)
            session.add(plan)

        inputs = gather_inputs(session, user_id, today)
        goal = session.scalar(select(Goal).where(Goal.user_id == user_id))
        if inputs.goal_active:
            _remember_progress(goal, inputs.learned_up_to)
        if new_day:
            # 新的一天：强度回到目标定的默认档；选了“几天冲刺”的补法时，这几天默认冲刺。
            default = _loads(goal.summary_json, {}).get("default_intensity") if goal else None
            plan.intensity = default if default in INTENSITY else DEFAULT_INTENSITY
            if inputs.learn_mode == "sprint":
                plan.intensity = "sprint"
        _add_drafts(session, user_id, plan, scheduler.schedule(inputs), keep=[])

        if new_day:
            _expire_old_cards(session, user_id, day)
            ctx = _return_context(session, user_id, today, _last_open_before(session, user_id, day))
            kind = returning.classify(ctx)
            if kind:
                _add_card(session, user_id, day, kind, ctx, suffix="")
        plan_id = plan.id
        try:
            session.commit()
        except IntegrityError:
            # 同时来了两个请求，另一个已经排好了，用它的。
            session.rollback()
        return plan_id


# ---------- 中断后回来的卡：出卡、接受、撤销、先不用 ----------


def _card_meta(row: AgentAction) -> dict[str, Any]:
    return _loads(row.suggestion_json, {})


def _is_plan_card(row: Optional[AgentAction], user_id: str) -> bool:
    return row is not None and row.user_id == user_id and bool(_card_meta(row).get("plan_line"))


def _add_card(session, user_id: str, day: str, kind: str, ctx: returning.ReturnContext, *, suffix: str) -> AgentAction:
    card = returning.build_card(kind, ctx)
    card.update({"plan_line": True, "day": day, "label": returning.BADGE})
    row = AgentAction(
        id=f"{user_id}:return:{day}{suffix}",
        user_id=user_id,
        trigger="return",
        suggestion_json=json.dumps(card, ensure_ascii=False),
        status="pending",
        before_json="{}",
        after_json="{}",
    )
    session.add(row)
    return row


def _expire_old_cards(session, user_id: str, day: str) -> None:
    rows = session.scalars(
        select(AgentAction).where(AgentAction.user_id == user_id, AgentAction.status == "pending")
    ).all()
    for row in rows:
        meta = _card_meta(row)
        if meta.get("plan_line") and str(meta.get("day", "")) < day:
            row.status = "expired"


def _card_view(row: AgentAction) -> dict[str, Any]:
    meta = _card_meta(row)
    return {
        "id": row.id,
        "kind": meta.get("kind"),
        "type": meta.get("type"),
        "title": meta.get("title"),
        "lines": meta.get("lines", []),
        "badge": meta.get("badge", returning.BADGE),
        "collapsed_text": meta.get("collapsed_text", ""),
        "decline_label": meta.get("decline_label", "先不用"),
        "options": [
            {key: value for key, value in option.items() if key != "effect"}
            for option in meta.get("options", [])
        ],
        "chosen": meta.get("chosen_option") or (meta.get("chosen") if isinstance(meta.get("chosen"), str) else None),
        "phases": (meta.get("breakdown") or {}).get("phases"),
        "status": row.status,
    }


def _pending_card(session, user_id: str, day: str) -> Optional[AgentAction]:
    rows = session.scalars(
        select(AgentAction)
        .where(AgentAction.user_id == user_id, AgentAction.status == "pending")
        .order_by(AgentAction.id)
    ).all()
    cards = [row for row in rows if _card_meta(row).get("plan_line") and _card_meta(row).get("day") == day]
    return cards[-1] if cards else None


def is_plan_card(user_id: str, action_id: str) -> bool:
    with SessionLocal() as session:
        return _is_plan_card(session.get(AgentAction, action_id), user_id)


def card_kind(user_id: str, action_id: str) -> Optional[str]:
    """计划线卡片的种类；不是计划线的卡返回 None。"""
    with SessionLocal() as session:
        row = session.get(AgentAction, action_id)
        return str(_card_meta(row).get("kind")) if _is_plan_card(row, user_id) else None


def needs_setup(goal: Optional[Goal]) -> bool:
    """还没在目标拆解卡上点过“好”（或撤销了），前端该开始问目标。"""
    if goal is None:
        return True
    return goal.status == "draft" or not _loads(goal.summary_json, {}).get("confirmed")


def _snapshot(plan: PlanDay, goal: Goal) -> dict[str, Any]:
    summary = _loads(goal.summary_json, {})
    return {
        "intensity": plan.intensity,
        "goal_status": goal.status,
        "exam_date": goal.exam_date,
        "pace": summary.get("pace"),
        "review_floor": summary.get("review_floor"),
    }


def _restore(plan: PlanDay, goal: Goal, snap: dict[str, Any]) -> None:
    plan.intensity = snap.get("intensity") or DEFAULT_INTENSITY
    goal.status = snap.get("goal_status") or goal.status
    goal.exam_date = snap.get("exam_date") if snap.get("exam_date") is not None else goal.exam_date
    summary = _loads(goal.summary_json, {})
    for key in ("pace", "review_floor"):
        if snap.get(key) is None:
            summary.pop(key, None)
        else:
            summary[key] = snap[key]
    goal.summary_json = json.dumps(summary, ensure_ascii=False)


def _rebuild_today(session, user_id: str, plan: PlanDay, today: date) -> None:
    """改了安排后重排今天：做完的保留，没做的换成新算的，总数仍不超过三件。"""
    session.flush()
    tasks = _plan_tasks(session, user_id, plan.id)
    done = [task for task in tasks if task.status == "done"]
    for task in tasks:
        if task.status != "done":
            session.delete(task)
    session.flush()
    _add_drafts(session, user_id, plan, scheduler.schedule(gather_inputs(session, user_id, today)), keep=done)


class CardError(ValueError):
    pass


def accept_card(
    user_id: str, action_id: str, *, option: Optional[str] = None, exam_date: Optional[str] = None
) -> Optional[dict[str, Any]]:
    """用户点了卡上的一个选项：这时才生效，存下改之前 / 改之后，可撤销。"""
    plan_id = ensure_today_plan(user_id)
    today = today_for(user_id)
    with SessionLocal() as session:
        row = session.get(AgentAction, action_id)
        if not _is_plan_card(row, user_id):
            return None
        if row.status != "pending":
            raise CardError("这张卡已经处理过了")
        meta = _card_meta(row)
        options = meta.get("options") or []
        picked = next((item for item in options if item.get("id") == option), None)
        if picked is None and option is None and len(options) == 1:
            picked = options[0]
        if picked is None:
            raise CardError("请选卡上的一个选项")
        plan = session.get(PlanDay, plan_id)
        goal = session.scalar(select(Goal).where(Goal.user_id == user_id))
        assert plan is not None and goal is not None
        before = _snapshot(plan, goal)

        effect = picked.get("effect") or {}
        summary = _loads(goal.summary_json, {})
        if picked.get("needs") == "exam_date":
            new_date = _local_date(exam_date or "")
            if new_date is None or new_date <= today:
                raise CardError("请给一个今天之后的考试日期（YYYY-MM-DD）")
            goal.exam_date = new_date.isoformat()
        if "intensity" in effect:
            plan.intensity = effect["intensity"]
        if "goal_status" in effect:
            goal.status = effect["goal_status"]
        if "pace" in effect:
            summary["pace"] = effect["pace"]
        if "review_floor" in effect:
            summary["review_floor"] = effect["review_floor"]
        goal.summary_json = json.dumps(summary, ensure_ascii=False)

        meta["chosen"] = picked.get("id")
        row.suggestion_json = json.dumps(meta, ensure_ascii=False)
        row.status = "executed"
        row.before_json = json.dumps(before, ensure_ascii=False)
        row.after_json = json.dumps(_snapshot(plan, goal), ensure_ascii=False)
        _rebuild_today(session, user_id, plan, today)

        # 目标卡选了“照旧 / 日期变了”：如果确实落后，接着出下一张（一次只一张）。
        next_row = None
        if meta.get("kind") == returning.KIND_GOAL and picked.get("id") in ("keep", "exam_date"):
            session.flush()
            ctx = _return_context(session, user_id, today, None)
            follow = returning.behind_kind(ctx)
            if follow != returning.KIND_GOAL:
                next_row = _add_card(session, user_id, plan.day, follow, ctx, suffix=":next")
        session.commit()
        session.refresh(row)
        data = _card_view(row)
        data["next_card"] = _card_view(next_row) if next_row is not None else None
    data["plan"] = plan_today(user_id)
    return data


def undo_card(user_id: str, action_id: str) -> Optional[dict[str, Any]]:
    """撤销：恢复改之前的状态，重排今天还没开始的任务。"""
    plan_id = ensure_today_plan(user_id)
    today = today_for(user_id)
    with SessionLocal() as session:
        row = session.get(AgentAction, action_id)
        if not _is_plan_card(row, user_id):
            return None
        if row.status != "executed":
            raise CardError("这张卡还没生效，不用撤销")
        plan = session.get(PlanDay, plan_id)
        goal = session.scalar(select(Goal).where(Goal.user_id == user_id))
        assert plan is not None and goal is not None
        _restore(plan, goal, _loads(row.before_json, {}))
        row.status = "undone"
        # 它带出来的下一张卡还没点的话，一起收起，避免同时有两件事要决定。
        child = session.get(AgentAction, f"{action_id}:next")
        if child is not None and child.status == "pending":
            child.status = "expired"
        _rebuild_today(session, user_id, plan, today)
        session.commit()
        session.refresh(row)
        data = _card_view(row)
    data["plan"] = plan_today(user_id)
    return data


def dismiss_card(user_id: str, action_id: str) -> Optional[dict[str, Any]]:
    """先不用：什么都不改，卡收起。"""
    with SessionLocal() as session:
        row = session.get(AgentAction, action_id)
        if not _is_plan_card(row, user_id):
            return None
        if row.status != "pending":
            raise CardError("这张卡已经处理过了")
        row.status = "declined"
        session.commit()
        session.refresh(row)
        return _card_view(row)


# ---------- 对外 ----------


def _minute_shares(total: int, count: int) -> list[int]:
    if count <= 0:
        return []
    base, extra = divmod(total, count)
    return [base + (1 if index < extra else 0) for index in range(count)]


def _task_view(row: PlanTask, intensity: str, minutes: Optional[int] = None) -> dict[str, Any]:
    ref = _loads(row.ref_json, {})
    text = scheduler.describe(row.kind, ref, intensity) if ref.get("source") else {}
    data = {
        "id": row.id,
        "kind": row.kind,
        "kind_label": KIND_LABEL.get(row.kind, row.kind),
        "title": text.get("title") or row.title,
        "status": row.status,
        "done_when": text.get("done_when") or row.done_when,
        "ref": ref,
        "amount": text.get("amount", ""),
        "reason": text.get("reason", ""),
    }
    if minutes is not None:
        data["minutes"] = minutes
    return data


def plan_today(user_id: str) -> dict[str, Any]:
    plan_id = ensure_today_plan(user_id)
    with SessionLocal() as session:
        plan = session.get(PlanDay, plan_id)
        assert plan is not None
        tasks = _plan_tasks(session, user_id, plan_id)
        label, minutes = INTENSITY.get(plan.intensity, INTENSITY[DEFAULT_INTENSITY])
        items = [
            _task_view(task, plan.intensity, share)
            for task, share in zip(tasks, _minute_shares(minutes, len(tasks)))
        ]
        first = next((item["id"] for item in items if item["status"] == "todo"), None)
        card = _pending_card(session, user_id, plan.day)
        goal = session.scalar(select(Goal).where(Goal.user_id == user_id))
        all_done = bool(items) and first is None
        done = None
        if all_done:
            summary = _loads(goal.summary_json, {}) if goal else {}
            learned = summary.get("learned_up_to")
            done = daily.done_card(
                items,
                _tomorrow_tasks(session, user_id, date.fromisoformat(plan.day)),
                milestone=daily.milestone_text(
                    [item["ref"] for item in items if item["kind"] == "learn"],
                    learned_up_to=learned if isinstance(learned, int) else 0,
                    lecture_count=goal.lecture_count if goal else 0,
                ),
            )
        setup = needs_setup(goal)
        first_item = next((item for item in items if item["id"] == first), None)
        return {
            "date": plan.day,
            "intensity": plan.intensity,
            "intensity_label": label,
            "minutes": minutes,
            "tasks": items,
            "first_task_id": first,
            "all_done": all_done,
            "card": _card_view(card) if card is not None else None,
            "done_card": done,
            "needs_setup": setup,
            "mood": "celebrate" if all_done else ("rest" if not items else "hello"),
            "quick_replies": daily.quick_replies(
                needs_setup=setup,
                has_card=card is not None,
                intensity=plan.intensity,
                first_task=first_item,
                all_done=all_done,
                has_tasks=bool(items),
            ),
            "label": "模拟",
        }


def _tomorrow_tasks(session, user_id: str, today: date) -> list[dict[str, Any]]:
    """收工卡上预告明天的三件（只算不存；明天打开时按当时的记录再排一次）。"""
    tomorrow = today + timedelta(days=1)
    inputs = gather_inputs(session, user_id, tomorrow)
    goal = session.scalar(select(Goal).where(Goal.user_id == user_id))
    level = (_loads(goal.summary_json, {}).get("default_intensity") if goal else None) or DEFAULT_INTENSITY
    if inputs.learn_mode == "sprint":
        level = "sprint"
    out = []
    for draft in scheduler.schedule(inputs):
        text = scheduler.describe(draft.kind, draft.ref, level)
        out.append({"kind": draft.kind, "kind_label": KIND_LABEL[draft.kind], "title": text["title"], "ref": draft.ref})
    return out


def set_intensity(user_id: str, intensity: str) -> dict[str, Any]:
    """用户自己在左栏切强度：直接生效，件数不变。"""
    if intensity not in INTENSITY:
        raise ValueError("intensity 只能是 light、normal 或 sprint")
    plan_id = ensure_today_plan(user_id)
    with SessionLocal() as session:
        plan = session.get(PlanDay, plan_id)
        assert plan is not None
        plan.intensity = intensity
        session.commit()
    return plan_today(user_id)


def patch_task(user_id: str, task_id: str, *, status: Optional[str] = None) -> Optional[dict[str, Any]]:
    """勾选 / 取消勾选。勾完“学新的”推进进度（一次两讲时推进到后一讲）；完成记录不删。"""
    base = store.patch_task(user_id, task_id, status=status)
    if base is None:
        return None
    with SessionLocal() as session:
        row = session.get(PlanTask, task_id)
        if row is None or row.user_id != user_id:
            return None
        plan = session.get(PlanDay, row.plan_day_id)
        intensity = plan.intensity if plan else DEFAULT_INTENSITY
        ref = _loads(row.ref_json, {})
        last = scheduler.last_lecture_no(ref)
        first = scheduler.first_lecture_no(ref)
        if row.kind == "learn" and last is not None and first is not None and status in ("done", "todo"):
            goal = session.scalar(select(Goal).where(Goal.user_id == user_id))
            if goal is not None:
                summary = _loads(goal.summary_json, {})
                current = summary.get("learned_up_to")
                current = current if isinstance(current, int) else 0
                if status == "done" and last > current:
                    _remember_progress(goal, last)
                elif status == "todo" and current == last:
                    _remember_progress(goal, first - 1)
                session.commit()
        data = _task_view(row, intensity)
        task_day = row.day
    today = plan_today(user_id)
    if task_day == today["date"]:
        nxt = next((t for t in today["tasks"] if t["id"] == today["first_task_id"]), None)
        data["next"] = daily.next_prompt(nxt)
        data["all_done"] = today["all_done"]
        data["done_card"] = today["done_card"]
    return data


def task_later(user_id: str, task_id: str) -> Optional[dict[str, Any]]:
    """“晚点再做”：这件挪到最后，先带下一件。用户自己的操作，直接生效。"""
    ensure_today_plan(user_id)
    with SessionLocal() as session:
        row = session.get(PlanTask, task_id)
        if row is None or row.user_id != user_id:
            return None
        if row.status == "todo":
            tasks = _plan_tasks(session, user_id, row.plan_day_id)
            row.sort_order = max((t.sort_order for t in tasks), default=0) + 1
            session.commit()
    return plan_today(user_id)


def adjust_from_text(user_id: str, text: str) -> dict[str, Any]:
    """用户说“今天只有 15 分钟”这类话：出一张调强度的建议卡，点了才换。

    问答线识别到“调安排”时可以直接调这个函数。
    """
    plan_id = ensure_today_plan(user_id)
    target = daily.wanted_intensity(text)
    with SessionLocal() as session:
        plan = session.get(PlanDay, plan_id)
        assert plan is not None
        pending = _pending_card(session, user_id, plan.day)
        if pending is not None:
            return {"understood": target is not None, "card": _card_view(pending), "reply": "先把这张卡定下来，再说别的"}
        if target is None:
            return {"understood": False, "card": None, "reply": daily.NOT_UNDERSTOOD}
        if target == plan.intensity:
            return {"understood": True, "card": None, "reply": daily.same_level_reply(target)}
        card = daily.adjust_card(target)
        card.update({"plan_line": True, "day": plan.day, "label": daily.BADGE})
        row = AgentAction(
            id=f"{user_id}:adjust:{uuid.uuid4().hex[:10]}",
            user_id=user_id,
            trigger="adjust",
            suggestion_json=json.dumps(card, ensure_ascii=False),
            status="pending",
            before_json="{}",
            after_json="{}",
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"understood": True, "card": _card_view(row), "reply": ""}
