"""把五条线的路由收成一个，供 install 挂到 /api。"""

from __future__ import annotations

from fastapi import APIRouter

from app.study.dashboard import router as dashboard_router
from app.study.materials.routes import router as materials_router
from app.study.plan import router as plan_router
from app.study.practice import router as practice_router
from app.study.qa import router as qa_router

router = APIRouter()
router.include_router(materials_router)
router.include_router(qa_router)
router.include_router(practice_router)
router.include_router(plan_router)
router.include_router(dashboard_router)

# 启动时决定是否注册；关闭时不暴露任何 V2 接口。
from app.study.v2 import enabled

if enabled():
    from app.study.v2.routes import router as v2_router

    router.include_router(v2_router)
