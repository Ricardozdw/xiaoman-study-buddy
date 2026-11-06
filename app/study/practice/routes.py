"""练习线接口。保留原有三个入口，可选字段向后兼容。"""

from __future__ import annotations

from datetime import date
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.auth import require_user
from app.study.common.http import pack
from app.study.practice import service
from app.study.practice.capabilities import PracticeError
from app.study.practice.schemas import AttemptBody, ProgressBody, QuizBody, ReportBody

router = APIRouter(tags=["练习"])


@router.get("/api/practice/materials")
def practice_materials(user_id: str = Depends(require_user)):
    from app.study.practice.uploads import material_list
    return pack(material_list(user_id), mock=False)


@router.post("/api/practice/materials")
async def practice_upload(file: UploadFile = File(...), user_id: str = Depends(require_user)):
    from app.study.practice.uploads import upload
    return pack(await upload(user_id, file), mock=False)


@router.get("/api/practice/status")
def practice_status(user_id: str = Depends(require_user)):
    from app.gateway.config import get_config
    from app.gateway.llm_gateway import ModelTier, has_llm
    configured = has_llm(ModelTier.STRONG)
    return pack({"configured": configured, "model_chain": [m.model for m in get_config().chain("strong")],
                 "note": "模型已配置，出题时会实际调用；本状态不代替连通性测试。" if configured else "未配置模型，当前只能体验模拟题。"},
                mock=not configured)


def _run(fn, *args):
    try:
        data = fn(*args)
        return pack(data, mock=bool(data.get("mock", False)))
    except LookupError:
        raise HTTPException(404, detail={"code": "not_found", "message": "没有找到这条练习记录"}) from None
    except PracticeError as exc:
        raise HTTPException(422, detail={"code": "practice_unavailable", "message": str(exc)}) from None


@router.post("/api/quizzes")
def quizzes(body: QuizBody, user_id: str = Depends(require_user)):
    return _run(service.create_quiz, user_id, body)


@router.get("/api/quizzes/{quiz_id}")
def quiz_detail(quiz_id: str, user_id: str = Depends(require_user)):
    return _run(service.get_quiz, user_id, quiz_id)


@router.patch("/api/quizzes/{quiz_id}/progress")
def quiz_progress(quiz_id: str, body: ProgressBody, user_id: str = Depends(require_user)):
    return _run(service.save_progress, user_id, quiz_id, body)


@router.post("/api/attempts")
def attempts(body: AttemptBody, user_id: str = Depends(require_user)):
    return _run(service.submit, user_id, body)


@router.get("/api/mistakes")
def mistakes(user_id: str = Depends(require_user)):
    return _run(service.mistakes, user_id)


@router.get("/api/practice/review-due")
def review_due(on: date | None = None, user_id: str = Depends(require_user)):
    return _run(service.review_due, user_id, on)


@router.get("/api/practice/stats")
def stats(lecture_id: str = "", user_id: str = Depends(require_user)):
    return _run(service.stats, user_id, lecture_id)


@router.get("/api/practice/paused")
def paused(user_id: str = Depends(require_user)):
    return _run(service.paused_quizzes, user_id)


@router.get("/api/practice/learning")
def learning_items(lecture_id: str = "", user_id: str = Depends(require_user)):
    return _run(service.learning_items, user_id, lecture_id)


def _feedback_run(fn, *args):
    from sqlalchemy.exc import SQLAlchemyError
    try:
        return _run(fn, *args)
    except SQLAlchemyError:
        raise HTTPException(503, detail={"code": "feedback_save_failed", "message": "反馈未保存，请重试。你填写的内容已保留。"}) from None


@router.post("/api/practice/reports")
def reports(body: ReportBody, user_id: str = Depends(require_user)):
    return _feedback_run(service.report, user_id, body.question_id, body.reason, body.category, body.quiz_id, body.attempt_id)


@router.get("/api/practice/reports/{question_id}")
def report_detail(question_id: str, user_id: str = Depends(require_user)):
    from app.study.practice.reports import get_report
    return _run(get_report, user_id, question_id)


@router.delete("/api/practice/reports/{question_id}")
def withdraw_feedback(question_id: str, user_id: str = Depends(require_user)):
    from app.study.practice.reports import withdraw_report
    return _feedback_run(withdraw_report, user_id, question_id)
