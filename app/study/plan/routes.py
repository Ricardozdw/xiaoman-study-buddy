"""计划线接口：目标、今天三件、建议、授权开关。今天三件走 service.py 的排程规则。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth import require_user
from app.study.common import store
from app.study.common.http import missing, pack
from app.study.plan import demo, goal, service

router = APIRouter(tags=["计划"])


class GoalBody(BaseModel):
    title: str = ""
    exam_date: str = ""
    lecture_count: int = 0
    daily_minutes: int = 0


class GoalDraftBody(BaseModel):
    """目标拆解的回答。没答或跳过的项不填；听不懂的按默认值，并在卡上写明“先按……安排”。"""

    title: Optional[str] = None
    exam_date: Optional[str] = Field(default=None, description="自由输入，如“12月20日”“两个月后”“还没定”")
    lecture_count: Optional[str] = Field(default=None, description="如“12 讲”“十二讲”")
    learned_up_to: Optional[str] = Field(default=None, description="如“第 3 讲”“还没开始”")
    daily_minutes: Optional[str] = Field(default=None, description="如“30 分钟”“半小时”")
    intensity: Optional[str] = Field(default=None, description="可选：light / normal / sprint")


class ReviseBody(BaseModel):
    text: str = Field(description="一句话说怎么改，如“考试改到 12 月 20 日”")


class TaskPatch(BaseModel):
    status: Optional[str] = None


class IntensityPatch(BaseModel):
    intensity: str = Field(description="light 轻松 / normal 正常 / sprint 冲刺")


class AcceptBody(BaseModel):
    option: Optional[str] = Field(default=None, description="选了卡上的哪个选项；只有一个选项时可以不填")
    exam_date: Optional[str] = Field(default=None, description="选“考试日期变了”时带上新日期 YYYY-MM-DD")


class DemoStep(BaseModel):
    days: int = Field(description="往后跳几天：1 跳到明天，2 跳过两天，8 跳过 8 天")


class PermissionPatch(BaseModel):
    permissions: dict[str, Any] = Field(default_factory=dict)


@router.post("/api/goals")
def save_goal(body: GoalBody, user_id: str = Depends(require_user)):
    """用户自己直接改目标：直接生效（不经过拆解卡）。"""
    return pack(
        goal.save_direct(
            user_id,
            title=body.title,
            exam_date=body.exam_date,
            lecture_count=body.lecture_count,
            daily_minutes=body.daily_minutes,
        )
    )


@router.get("/api/goals/current")
def current_goal(user_id: str = Depends(require_user)):
    return pack(goal.current(user_id))


@router.get("/api/goals/questions")
def goal_questions(user_id: str = Depends(require_user)):
    """第一次见面问的几道题，每题带快捷回复。一次问一题。"""
    return pack(goal.questions())


@router.post("/api/goals/draft")
def goal_draft(body: GoalDraftBody, user_id: str = Depends(require_user)):
    """按回答出一张目标拆解卡。点“好”（accept）才生效。"""
    return pack(goal.draft(user_id, body.model_dump()))


@router.post("/api/goals/draft/{action_id}/revise")
def goal_revise(action_id: str, body: ReviseBody, user_id: str = Depends(require_user)):
    """“说说怎么改”：一句话改，出一张新卡替换旧卡。"""
    try:
        data = goal.revise(user_id, action_id, body.text)
    except service.CardError as exc:
        return pack({"message": str(exc)}, ok=False, status="invalid", code=422)
    if data is None:
        missing()
    return pack(data)


@router.get("/api/plan/today")
def today(user_id: str = Depends(require_user)):
    return pack(service.plan_today(user_id))


@router.patch("/api/plan/today")
def today_intensity(body: IntensityPatch, user_id: str = Depends(require_user)):
    try:
        data = service.set_intensity(user_id, body.intensity)
    except ValueError as exc:
        return pack({"message": str(exc)}, ok=False, status="invalid", code=422)
    return pack(data)


@router.patch("/api/tasks/{task_id}")
def patch_task(task_id: str, body: TaskPatch, user_id: str = Depends(require_user)):
    try:
        data = service.patch_task(user_id, task_id, status=body.status)
    except ValueError as exc:
        return pack({"message": str(exc)}, ok=False, status="invalid", code=422)
    if data is None:
        missing()
    return pack(data)


@router.get("/api/suggestions")
def suggestions(user_id: str = Depends(require_user)):
    return pack(store.list_suggestions(user_id))


@router.post("/api/suggestions/{action_id}/accept")
def accept(action_id: str, body: Optional[AcceptBody] = None, user_id: str = Depends(require_user)):
    """计划线的卡（中断后回来）走 service；地基那条样例建议仍走原来的。"""
    kind = service.card_kind(user_id, action_id)
    if kind == goal.KIND_GOAL_SETUP:
        try:
            data = goal.accept(user_id, action_id)
        except service.CardError as exc:
            return pack({"message": str(exc)}, ok=False, status="invalid", code=422)
    elif kind is not None:
        try:
            data = service.accept_card(
                user_id, action_id, option=body.option if body else None, exam_date=body.exam_date if body else None
            )
        except service.CardError as exc:
            return pack({"message": str(exc)}, ok=False, status="invalid", code=422)
    else:
        data = store.accept_suggestion(user_id, action_id)
    if data is None:
        missing()
    return pack(data)


@router.post("/api/suggestions/{action_id}/dismiss")
def dismiss(action_id: str, user_id: str = Depends(require_user)):
    """先不用：什么都不改，卡收起。只用于计划线的卡。"""
    try:
        data = service.dismiss_card(user_id, action_id)
    except service.CardError as exc:
        return pack({"message": str(exc)}, ok=False, status="invalid", code=422)
    if data is None:
        missing()
    return pack(data)


@router.post("/api/actions/{action_id}/undo")
def undo(action_id: str, user_id: str = Depends(require_user)):
    kind = service.card_kind(user_id, action_id)
    if kind == goal.KIND_GOAL_SETUP:
        try:
            data = goal.undo(user_id, action_id)
        except service.CardError as exc:
            return pack({"message": str(exc)}, ok=False, status="invalid", code=422)
    elif kind is not None:
        try:
            data = service.undo_card(user_id, action_id)
        except service.CardError as exc:
            return pack({"message": str(exc)}, ok=False, status="invalid", code=422)
    else:
        data = store.undo_action(user_id, action_id)
    if data is None:
        missing()
    return pack(data)


@router.get("/api/me/permissions")
def permissions_get(user_id: str = Depends(require_user)):
    """合同只写了 PATCH。多留一个 GET，方便页面读当前开关。"""
    return pack(store.permissions(user_id))


@router.patch("/api/me/permissions")
def permissions(body: PermissionPatch, user_id: str = Depends(require_user)):
    return pack(store.patch_permissions(user_id, body.permissions))


# ---------- 演示开关（只在 XIAOMAN_DEMO_CLOCK=1 时可用，界面标“演示用”）----------


@router.get("/api/demo/clock")
def demo_clock(user_id: str = Depends(require_user)):
    return pack(demo.view(user_id))


@router.post("/api/demo/clock")
def demo_clock_advance(body: DemoStep, user_id: str = Depends(require_user)):
    if not demo.enabled():
        missing()
    try:
        data = demo.advance(user_id, body.days)
    except ValueError as exc:
        return pack({"message": str(exc)}, ok=False, status="invalid", code=422)
    return pack(data)


@router.post("/api/demo/clock/reset")
def demo_clock_reset(user_id: str = Depends(require_user)):
    if not demo.enabled():
        missing()
    return pack(demo.reset(user_id))
