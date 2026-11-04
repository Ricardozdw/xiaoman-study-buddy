"""统一的学习接口外壳。mock 表示这是地基假数据或离线占位。"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


class Envelope(BaseModel):
    ok: bool = True
    status: str = "ok"
    mock: bool = True
    data: dict[str, Any] = Field(default_factory=dict)


def pack(data: dict[str, Any], *, ok: bool = True, status: str = "ok", mock: bool = True, code: int = 200) -> JSONResponse:
    return JSONResponse({"ok": ok, "status": status, "mock": mock, "data": data}, status_code=code)


def missing() -> None:
    raise HTTPException(status_code=404, detail={"code": "not_found", "message": "没有找到这条记录"})
