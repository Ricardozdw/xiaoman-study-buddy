"""仅供离线评测：隔离数据库里的公开、人工构造统计记录。"""
import uuid
from datetime import date

from app.data_access.session import SessionLocal
from app.study.common import models
from app.study.common.db import ensure_schema
from app.study.dashboard.service import snapshot

MODELS = {name: getattr(models, name) for name in (
    "Question", "Attempt", "StudyEvent", "Chapter", "KnowledgePoint", "Goal", "Course", "PlanTask",
)}


def run(payload: dict) -> dict:
    ensure_schema()
    uid = "eval-" + uuid.uuid4().hex
    with SessionLocal() as session:
        for entry in payload.get("rows", []):
            row = dict(entry["data"])
            row["user_id"] = uid if row.pop("owner", "self") == "self" else uid + "-other"
            # IDs are namespaced so running the same case twice is independent.
            for key in ("id", "question_id", "course_id", "goal_id", "plan_day_id", "knowledge_point_id"):
                if row.get(key):
                    row[key] = uid + ":" + row[key]
            session.add(MODELS[entry["table"]](**row))
        session.commit()
    return snapshot(uid, today=date.fromisoformat(payload.get("today", "2026-11-06")))
