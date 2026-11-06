"""计划线接口：目标、今天三件、建议、授权开关。今天三件走 service.py 的排程规则。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth import require_user
from app.study.common import store
from app.study.common.http import missing, pack
from app.study.plan import demo, service

router = APIRouter(tags=["计划"])


class GoalBody(BaseModel):
    title: str = ""
    exam_date: str = ""
    lecture_count: int = 0
    daily_minutes: int = 0


class TaskPatch(BaseModel):
    status: Optional[str] = None


class IntensityPatch(BaseModel):
    intensity: str = Field(description="light 轻松 / normal 正常 / sprint 冲刺")


class DemoStep(BaseModel):
    days: int = Field(description="往后跳几天：1 跳到明天，2 跳过两天，8 跳过 8 天")


class PermissionPatch(BaseModel):
    permissions: dict[str, Any] = Field(default_factory=dict)


@router.post("/api/goals")
def save_goal(body: GoalBody, user_id: str = Depends(require_user)):
    return pack(
        store.save_goal(
            user_id,
            title=body.title,
            exam_date=body.exam_date,
            lecture_count=body.lecture_count,
            daily_minutes=body.daily_minutes,
        )
    )


@router.get("/api/goals/current")
def current_goal(user_id: str = Depends(require_user)):
    return pack(store.goals_current(user_id))


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
def accept(action_id: str, user_id: str = Depends(require_user)):
    data = store.accept_suggestion(user_id, action_id)
    if data is None:
        missing()
    return pack(data)


@router.post("/api/actions/{action_id}/undo")
def undo(action_id: str, user_id: str = Depends(require_user)):
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
