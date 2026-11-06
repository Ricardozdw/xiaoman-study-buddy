"""Cross-line adapters preserving each capability owner's response contract."""
from __future__ import annotations

import json
import re


def practice_request(user_id: str, message: str, lecture_id: str) -> dict:
    from app.study.practice.routes import QuizBody, quizzes
    found = re.search(r"(\d+)\s*道", message)
    count = min(5, max(1, int(found[1]))) if found else 5
    response = quizzes(QuizBody(lecture_id=lecture_id, count=count), user_id=user_id)
    envelope = json.loads(response.body)
    return {**envelope["data"], "mock": envelope.get("mock", True)}


def plan_request(user_id: str, message: str) -> dict:
    """Return the plan owner's card or reply; decisions use formal plan APIs.

    The owner serializes its native options, enforces one pending card and owns
    acceptance/undo snapshots. Upstream study fixtures remain explicitly mock.
    """
    from app.study.plan.service import adjust_from_text

    return {**adjust_from_text(user_id, message), "mock": True, "label": "模拟"}
