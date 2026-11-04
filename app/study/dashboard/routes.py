"""看板占位，以及地基查看用量和 bad case 的观察口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.auth import require_user
from app.study.common import store
from app.study.common.capability import run_example
from app.study.common.http import pack

router = APIRouter(tags=["看板"])


class ExampleBody(BaseModel):
    text: str = Field(default="每天最多三件事。想多学就加强度，不加件数。")
    page: int = 1
    demo_failure: bool = False


@router.get("/api/dashboard")
def dashboard(range: str = Query("week"), user_id: str = Depends(require_user)):
    return pack(store.dashboard(user_id, range))


@router.post("/api/study/example")
def example(body: ExampleBody, user_id: str = Depends(require_user)):
    """AI 能力范例。demo_failure=true 时写一条测试用 bad case。"""
    result = run_example(user_id, body.text, page=body.page, demo_failure=body.demo_failure)
    ok = bool(result.get("ok"))
    return pack(result, ok=ok, status="ok" if ok else "bad_output", mock=bool(result.get("mock", True)))


@router.get("/api/study/usage")
def usage(user_id: str = Depends(require_user)):
    return pack(store.usage_for(user_id))


@router.get("/api/study/bad-cases")
def bad_cases(user_id: str = Depends(require_user)):
    return pack(store.bad_cases_for(user_id))
