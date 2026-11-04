"""练习线占位：样例题、判分、错题本。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth import require_user
from app.study.common import store
from app.study.common.http import missing, pack

router = APIRouter(tags=["练习"])


class QuizBody(BaseModel):
    lecture_id: str = ""
    count: int = Field(default=2, ge=1, le=5)


class AttemptBody(BaseModel):
    question_id: str
    answer: str = ""
    seconds: int = 0
    confidence: str = ""


@router.post("/api/quizzes")
def quizzes(body: QuizBody, user_id: str = Depends(require_user)):
    return pack(store.make_quiz(user_id, body.lecture_id, body.count))


@router.post("/api/attempts")
def attempts(body: AttemptBody, user_id: str = Depends(require_user)):
    data = store.grade_attempt(
        user_id,
        question_id=body.question_id,
        answer=body.answer,
        seconds=body.seconds,
        confidence=body.confidence,
    )
    if data is None:
        missing()
    return pack(data)


@router.get("/api/mistakes")
def mistakes(user_id: str = Depends(require_user)):
    return pack(store.list_mistakes(user_id))
