"""V2 学习流程接口；开关由聚合路由在启动时控制。"""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.auth import require_user
from app.study.common.http import pack
from . import assessment, completion, exam, lecture, mistakes, service, summary
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


class LectureBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    unit_no: int = Field(ge=1)


@router.get("/api/v2/mistakes")
def mistake_book(user_id: str = Depends(require_user)):
    data = mistakes.book(user_id)
    return pack(data, mock=data["mock"])


@router.get("/api/v2/today/summary")
def today_summary(user_id: str = Depends(require_user)):
    return pack(summary.today(user_id), mock=False)


@router.post("/api/v2/progress")
def advance_progress(body: LectureBody, user_id: str = Depends(require_user)):
    return pack(service.advance(user_id, body.unit_no), mock=False)


@router.post("/api/v2/lecture")
def unit_lecture(body: LectureBody, user_id: str = Depends(require_user)):
    outline_id = lecture.current_outline_id(user_id)
    if not outline_id:
        raise HTTPException(409, "还没有确认大纲")
    try:
        data, mock = lecture.generate(user_id, outline_id, body.unit_no, {})
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return pack(data, mock=mock)


def _pack_outline(data):
    return pack(data, mock=data.get("mock", False))


@router.get("/api/v2/outline/current")
def current_outline(user_id: str = Depends(require_user)):
    data = service.current(user_id)
    return pack({"outline": data}, mock=bool(data and data["mock"]))


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


class AssessmentSubmitBody(BaseModel):
    answers: dict[str, Literal["A", "B", "C", "D"]] = Field(max_length=10)


@router.get("/api/v2/assessment/due")
def assessment_due(user_id: str = Depends(require_user)):
    return pack(assessment.due(user_id), mock=False)


@router.post("/api/v2/assessment/start")
def assessment_start(user_id: str = Depends(require_user)):
    data = assessment.start(user_id)
    return pack(data, mock=data["mock"])


@router.post("/api/v2/assessment/{assessment_id}/submit")
def assessment_submit(assessment_id: str, body: AssessmentSubmitBody, user_id: str = Depends(require_user)):
    report, mock = assessment.submit(user_id, assessment_id, body.answers)
    return pack(report, mock=mock)


@router.post("/api/v2/exam/start")
def exam_start(user_id: str = Depends(require_user)):
    data = exam.start(user_id)
    return pack(data, mock=bool(data.get("mock")))


@router.post("/api/v2/exam/{exam_id}/submit")
def exam_submit(exam_id: str, body: AssessmentSubmitBody, user_id: str = Depends(require_user)):
    report, mock = exam.submit(user_id, exam_id, body.answers)
    return pack(report, mock=mock)


class CompletionConfirmBody(BaseModel):
    reason: Literal["suggested", "user_said"]


@router.get("/api/v2/completion")
def completion_status(user_id: str = Depends(require_user)):
    data = completion.status(user_id)
    return pack(data, mock=bool(data["card"] and data["card"]["label"]))


@router.post("/api/v2/completion/confirm")
def completion_confirm(body: CompletionConfirmBody, user_id: str = Depends(require_user)):
    card = completion.confirm(user_id, body.reason)
    return pack(card, mock=bool(card["label"]))


@router.post("/api/v2/completion/undo")
def completion_undo(user_id: str = Depends(require_user)):
    return pack(completion.undo(user_id), mock=False)
