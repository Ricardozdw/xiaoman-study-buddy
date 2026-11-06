"""计划线：读学习记录 → 交给排程规则 → 存成当天计划。

- 当天第一次打开时算一次，存进 plan_days / plan_tasks；同一天再打开不重新洗牌。
- 没做完的任务不搬到新的一天；新的一天重新算，仍最多三件。
- 新的一天强度回到“正常”（强度只算今天）。
- 勾完“学新的”，已学到第几讲 +1，明天自然排下一讲。
- 错题、掌握度、资料状态只读练习线和资料线的表，不改它们。
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.data_access.session import SessionLocal
from app.study.common import store
from app.study.common.models import (
    Attempt,
    Chapter,
    Goal,
    KnowledgePoint,
    PlanDay,
    PlanTask,
    Question,
    StudyFile,
)
from app.study.plan import demo, scheduler
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
    return PlanInputs(
        today=today,
        goal_active=(goal.status == "active"),
        lecture_count=lecture_count,
        learned_up_to=learned,
        lectures=tuple(lectures),
        mistakes=tuple(mistakes),
        reviews=tuple(reviews),
    )


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


def ensure_today_plan(user_id: str) -> str:
    """返回今天计划的 id；今天还没有就按规则排一份。"""
    store.seed(user_id)
    today = today_for(user_id)
    day = today.isoformat()
    with SessionLocal() as session:
        plan = session.scalar(select(PlanDay).where(PlanDay.user_id == user_id, PlanDay.day == day))
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
        for index, draft in enumerate(scheduler.schedule(inputs)):
            text = scheduler.describe(draft.kind, draft.ref, DEFAULT_INTENSITY)
            session.add(
                PlanTask(
                    id=f"{plan.id}:t{index + 1}",
                    user_id=user_id,
                    plan_day_id=plan.id,
                    day=day,
                    kind=draft.kind,
                    title=text["title"],
                    ref_json=json.dumps(draft.ref, ensure_ascii=False),
                    done_when=text["done_when"],
                    status="todo",
                    sort_order=index + 1,
                )
            )
        plan_id = plan.id
        try:
            session.commit()
        except IntegrityError:
            # 同时来了两个请求，另一个已经排好了，用它的。
            session.rollback()
        return plan_id


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
        return {
            "date": plan.day,
            "intensity": plan.intensity,
            "intensity_label": label,
            "minutes": minutes,
            "tasks": items,
            "first_task_id": first,
            "all_done": bool(items) and first is None,
            "label": "模拟",
        }


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
    """勾选 / 取消勾选。勾完“学新的”推进进度；完成记录不删。"""
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
        number = ref.get("lecture_no")
        if row.kind == "learn" and isinstance(number, int) and status in ("done", "todo"):
            goal = session.scalar(select(Goal).where(Goal.user_id == user_id))
            if goal is not None:
                summary = _loads(goal.summary_json, {})
                current = summary.get("learned_up_to")
                current = current if isinstance(current, int) else 0
                if status == "done" and number > current:
                    _remember_progress(goal, number)
                elif status == "todo" and current == number:
                    _remember_progress(goal, number - 1)
                session.commit()
        return _task_view(row, intensity)
