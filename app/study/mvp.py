"""MVP 表面开关。默认关闭，避免影响底座测试。

XIAOMAN_MVP=1 时，不暴露两周用不到的 HTTP 入口（飞书 / 微信、草稿、
安全输入区、记忆卡、渠道绑定）。危机识别在 /api/chat 里，出站护栏在
底座编排里，这里都不碰。
"""

from __future__ import annotations

import os

from starlette.responses import JSONResponse

# 前缀匹配。对话、会话、反馈、学习接口不在这里。
_BLOCKED_PREFIXES = (
    "/api/draft",
    "/api/secrets",
    "/api/memory",
    "/api/sandbox",
    "/api/channels",
    "/api/confirm",
    "/webhooks/feishu",
    "/webhooks/openclaw",
    "/bind",
    "/sandbox",
)


def mvp_enabled() -> bool:
    return (os.getenv("XIAOMAN_MVP") or "").strip().lower() in ("1", "true", "yes", "on")


def blocked(path: str) -> bool:
    raw = path or ""
    return any(raw == prefix or raw.startswith(prefix + "/") for prefix in _BLOCKED_PREFIXES)


class MvpSurfaceMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and mvp_enabled() and blocked(scope.get("path") or ""):
            body = {
                "detail": {
                    "code": "mvp_disabled",
                    "message": "地基阶段不暴露这个底座功能。危机识别和出站护栏仍在。",
                }
            }
            await JSONResponse(body, status_code=404)(scope, receive, send)
            return
        await self.app(scope, receive, send)
