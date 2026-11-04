"""bad case 写入。各线出错时调用 write_bad_case，不要各写各的表。"""

from __future__ import annotations

import json
import uuid
from typing import Any

from app.data_access.session import SessionLocal
from app.study.common.db import ensure_schema
from app.study.common.models import BadCase, _now


def write_bad_case(
    *,
    user_id: str,
    capability: str,
    input_payload: Any,
    actual_output: str,
    expected_output: str = "",
    model: str = "",
    prompt_version: str = "",
    problem_type: str = "格式错",
    severity: str = "低",
    status: str = "新",
    owner: str = "",
    fix_note: str = "",
    source: str = "backend",
) -> str:
    ensure_schema()
    row_id = uuid.uuid4().hex
    row = BadCase(
        id=row_id,
        user_id=user_id,
        capability=capability[:64],
        input_json=json.dumps(input_payload, ensure_ascii=False)[:8000],
        actual_output=(actual_output or "")[:8000],
        expected_output=(expected_output or "")[:8000],
        model=(model or "")[:128],
        prompt_version=(prompt_version or "")[:32],
        problem_type=problem_type[:32],
        severity=severity if severity in ("高", "中", "低") else "低",
        status=status[:16] or "新",
        owner=owner[:64],
        fix_note=(fix_note or "")[:2000],
        source=source[:32] or "backend",
        created_at=_now(),
    )
    with SessionLocal() as session:
        session.add(row)
        session.commit()
    return row_id
