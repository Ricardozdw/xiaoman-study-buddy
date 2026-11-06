"""V2 状态与学习大纲接口；开关由聚合路由在启动时控制。"""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.auth import require_user
from app.study.common.http import pack
from . import service
from .outline import Unit

router = APIRouter()


@router.get("/api/v2/status")
def status(user_id: str = Depends(require_user)):
    return pack({"enabled": True, "version": "2.0-min"}, mock=False)


class DraftBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    goal_type: Literal["exam", "course", "skill"]
    title: str = Field(min_length=1, max_length=200)
    deadline: date | None = None
    daily_minutes: int = Field(default=30, ge=5, le=600)
    progress: str = Field(default="", max_length=1000)
    materials: Literal["now", "later", "none"] = "none"


class PatchBody(BaseModel):
    units: list[Unit] = Field(min_length=1, max_length=20)


def _pack_outline(data):
    return pack(data, mock=data.get("mock", False))


@router.post("/api/v2/outline/draft")
def draft_outline(body: DraftBody, user_id: str = Depends(require_user)):
    return _pack_outline(service.draft(user_id, body.model_dump(mode="json")))


@router.patch("/api/v2/outline/{outline_id}")
def patch_outline(outline_id: str, body: PatchBody, user_id: str = Depends(require_user)):
    try:
        return _pack_outline(service.patch(user_id, outline_id, [unit.model_dump() for unit in body.units]))
    except ValueError:
        raise HTTPException(422, "请检查单元标题与要点，标题不能重复") from None


@router.post("/api/v2/outline/{outline_id}/accept")
def accept_outline(outline_id: str, user_id: str = Depends(require_user)):
    data = service.accept(user_id, outline_id)
    return pack(data, mock=data["outline"]["mock"])


@router.post("/api/v2/outline/{outline_id}/undo")
def undo_outline(outline_id: str, user_id: str = Depends(require_user)):
    return pack(service.undo(user_id, outline_id), mock=False)
