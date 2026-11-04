"""把学习包挂到底座应用上。main 里只应调用 install。"""

from __future__ import annotations


def install(app) -> None:
    from app.study.common.db import ensure_schema
    from app.study.mvp import MvpSurfaceMiddleware
    from app.study.router import router

    app.include_router(router)
    app.add_middleware(MvpSurfaceMiddleware)

    @app.on_event("startup")
    def _study_schema() -> None:
        ensure_schema()
