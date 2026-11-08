"""V2.2 错题本：复用练习线的错题判断（最后一次答错、按原题归并、做对了自动移出），
补上每讲标题和选项文字，按讲分组。只读本人数据，不调模型。"""
from __future__ import annotations

import json

from sqlalchemy import select

from app.data_access.session import SessionLocal
from app.study.common.db import ensure_schema
from app.study.common.models import Question
from app.study.plan import scheduler
from app.study.practice import service as practice_service

from .lecture import current_outline_id
from .models import GoalOutline


def book(user_id: str) -> dict:
    ensure_schema()
    raw = practice_service.mistakes(user_id)
    items = raw["items"]
    with SessionLocal() as session:
        ids = [item["question_id"] for item in items]
        options = {row.id: {o["id"]: o["text"] for o in json.loads(row.options_json or "[]")}
                   for row in session.scalars(select(Question).where(Question.user_id == user_id, Question.id.in_(ids)))}
        outline_id = current_outline_id(user_id)
        outline = session.scalar(select(GoalOutline).where(GoalOutline.id == outline_id, GoalOutline.user_id == user_id)) if outline_id else None
        titles = {unit.get("no", index + 1): unit["title"] for index, unit in enumerate(json.loads(outline.units_json))} if outline else {}
    groups: dict[int, dict] = {}
    for item in reversed(items):  # 最新错的在前
        no = scheduler.lecture_no_for(item["lecture_id"]) or 0
        group = groups.setdefault(no, {"lecture_no": no, "title": titles.get(no, ""), "items": []})
        texts = options.get(item["question_id"], {})
        group["items"].append({
            "question_id": item["question_id"], "stem": item["stem"], "analysis": item["analysis"],
            "your_answer": item["your_answer"], "your_answer_text": texts.get(item["your_answer"], ""),
            "answer": item["answer"], "answer_text": texts.get(item["answer"], ""),
        })
    return {"count": len(items), "groups": sorted(groups.values(), key=lambda g: g["lecture_no"]), "mock": raw["mock"]}
