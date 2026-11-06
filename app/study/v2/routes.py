"""V2 路由骨架；业务能力由后续任务卡实现。"""
from fastapi import APIRouter, Depends

from app.auth import require_user
from app.study.common.http import pack

router = APIRouter()


@router.get("/api/v2/status")
def status(user_id: str = Depends(require_user)):
    return pack({"enabled": True, "version": "2.0-min"}, mock=False)
