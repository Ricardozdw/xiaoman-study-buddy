"""演示开关：“跳到明天 / 跳过两天 / 跳过 8 天 / 回到今天”。

只在演示环境打开（XIAOMAN_DEMO_CLOCK=1），界面标“演示用”。
每个用户记一个“往后跳了几天”，写进 events 表（name=demo_clock，props 里是累计天数），
读最新一条。计划线的“今天” = 真实今天 + 这个数。开关关着时一律按真实日期。
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.data_access.session import SessionLocal
from app.study.common.db import ensure_schema
from app.study.common.models import StudyEvent, _now

_TZ = ZoneInfo("Asia/Shanghai")
EVENT_NAME = "demo_clock"
MAX_STEP_DAYS = 30
LABEL = "演示用"


def enabled() -> bool:
    return (os.getenv("XIAOMAN_DEMO_CLOCK") or "").strip().lower() in ("1", "true", "yes", "on")


def real_today() -> date:
    return datetime.now(_TZ).date()


def _stored_offset(user_id: str) -> int:
    ensure_schema()
    with SessionLocal() as session:
        row = session.scalars(
            select(StudyEvent)
            .where(StudyEvent.user_id == user_id, StudyEvent.name == EVENT_NAME)
            .order_by(StudyEvent.at.desc(), StudyEvent.id.desc())
            .limit(1)
        ).first()
    if row is None:
        return 0
    try:
        value = json.loads(row.props_json or "{}").get("offset_days", 0)
    except (json.JSONDecodeError, AttributeError):
        return 0
    return value if isinstance(value, int) and value >= 0 else 0


def offset_days(user_id: str) -> int:
    """开关关着时永远是 0，库里留着的记录不起作用。"""
    return _stored_offset(user_id) if enabled() else 0


def today(user_id: str) -> date:
    return real_today() + timedelta(days=offset_days(user_id))


def _write(user_id: str, offset: int, step: int) -> None:
    with SessionLocal() as session:
        session.add(
            StudyEvent(
                id=uuid.uuid4().hex,
                user_id=user_id,
                name=EVENT_NAME,
                at=_now(),
                props_json=json.dumps({"offset_days": offset, "step": step, "label": LABEL}, ensure_ascii=False),
            )
        )
        session.commit()


def advance(user_id: str, days: int) -> dict[str, Any]:
    if not 1 <= days <= MAX_STEP_DAYS:
        raise ValueError(f"days 只能是 1 到 {MAX_STEP_DAYS}")
    current = _stored_offset(user_id)
    _write(user_id, current + days, days)
    return view(user_id)


def reset(user_id: str) -> dict[str, Any]:
    _write(user_id, 0, -_stored_offset(user_id))
    return view(user_id)


def view(user_id: str) -> dict[str, Any]:
    offset = offset_days(user_id)
    real = real_today()
    return {
        "enabled": enabled(),
        "offset_days": offset,
        "today": (real + timedelta(days=offset)).isoformat(),
        "real_today": real.isoformat(),
        "label": LABEL,
    }
