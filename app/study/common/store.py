"""假数据的读写。形状按合同，规则不是各条线的正式算法。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.data_access.session import SessionLocal
from app.study.common.db import ensure_schema
from app.study.common.models import (
    AgentAction,
    Attempt,
    BadCase,
    Chapter,
    Course,
    Goal,
    KbDocument,
    KnowledgePoint,
    LlmCall,
    MaterialPage,
    Note,
    PlanDay,
    PlanTask,
    Question,
    StudyEvent,
    StudyFile,
    StudyMessage,
    UserSetting,
    _now,
)
from app.study.materials.content import SAMPLE_LECTURE_ID, SAMPLE_PAGES

_TZ = ZoneInfo("Asia/Shanghai")
INTENSITY = {
    "light": ("轻松", 15),
    "normal": ("正常", 30),
    "sprint": ("冲刺", 50),
}
KIND_LABEL = {"learn": "学新的", "practice": "练一练", "repair": "补一补"}


def today_str() -> str:
    return datetime.now(_TZ).date().isoformat()


def _sid(user_id: str, suffix: str) -> str:
    return f"{user_id}:{suffix}"


def seed(user_id: str) -> None:
    """每个用户第一次访问时写入一套样例。已有计划则不覆盖。"""
    ensure_schema()
    day = today_str()
    with SessionLocal() as session:
        existing = session.scalar(select(PlanDay.id).where(PlanDay.user_id == user_id))
        if existing:
            return
        goal_id = _sid(user_id, "goal")
        course_id = _sid(user_id, "course")
        chapter_id = _sid(user_id, "chapter")
        file_id = _sid(user_id, "file")
        kb_id = _sid(user_id, "kb")
        note_id = _sid(user_id, "note")
        point_id = _sid(user_id, "kp")
        question_id = _sid(user_id, "q1")
        plan_id = _sid(user_id, "plan")
        session.add(
            Goal(
                id=goal_id,
                user_id=user_id,
                title="用一门公开样例把学习搭子走通",
                exam_date="",
                status="active",
                lecture_count=8,
                daily_minutes=30,
                summary_json=json.dumps(
                    {
                        "phases": ["先交一讲样例", "每天最多三件", "考前再复习"],
                        "label": "模拟",
                    },
                    ensure_ascii=False,
                ),
                created_at=_now(),
            )
        )
        session.add(Course(id=course_id, user_id=user_id, goal_id=goal_id, title="公开样例课", sort_order=1))
        session.add(
            Chapter(
                id=chapter_id,
                user_id=user_id,
                course_id=course_id,
                title="第 6 讲",
                sort_order=6,
                lecture_id=SAMPLE_LECTURE_ID,
            )
        )
        session.add(
            StudyFile(
                id=file_id,
                user_id=user_id,
                filename="样例-第6讲.pdf",
                mime="application/pdf",
                storage_path=f"local://{file_id}",
                sha256="",
                parse_status="ready",
                lecture_id=SAMPLE_LECTURE_ID,
                created_at=_now(),
            )
        )
        session.add(KbDocument(id=kb_id, user_id=user_id, file_id=file_id, status="ready"))
        for item in SAMPLE_PAGES:
            session.add(
                MaterialPage(
                    id=_sid(user_id, f"page-{item['page']}"),
                    user_id=user_id,
                    lecture_id=SAMPLE_LECTURE_ID,
                    file_id=file_id,
                    page_no=item["page"],
                    text=item["text"],
                )
            )
        session.add(
            Note(
                id=note_id,
                user_id=user_id,
                lecture_id=SAMPLE_LECTURE_ID,
                title="第 6 讲 · 学习文档",
                content_json=json.dumps(
                    {
                        "label": "AI 整理，可以改",
                        "points": ["每天最多三件事", "想多学加强度，不加件数", "没做的不堆到今天"],
                        "terms": ["学新的", "练一练", "补一补"],
                        "mock": True,
                    },
                    ensure_ascii=False,
                ),
                edited_by_user=0,
                created_at=_now(),
            )
        )
        session.add(
            KnowledgePoint(
                id=point_id,
                user_id=user_id,
                lecture_id=SAMPLE_LECTURE_ID,
                name="每天三件事",
                explanation="学新的、练一练、补一补各一件。",
                source_json=json.dumps({"page": 1, "quote": SAMPLE_PAGES[0]["text"]}, ensure_ascii=False),
                mastery=40,
                next_review_on=day,
            )
        )
        session.add(
            Question(
                id=question_id,
                user_id=user_id,
                lecture_id=SAMPLE_LECTURE_ID,
                knowledge_point_id=point_id,
                kind="single",
                stem="想多学的时候，应该怎么做？",
                options_json=json.dumps(
                    [
                        {"id": "A", "text": "把今天的三件加到五件"},
                        {"id": "B", "text": "件数不变，把每件做深一点"},
                    ],
                    ensure_ascii=False,
                ),
                answer="B",
                analysis="强度变，件数不变。",
                source_json=json.dumps({"page": 1}, ensure_ascii=False),
                difficulty="easy",
            )
        )
        session.add(
            Question(
                id=_sid(user_id, "q2"),
                user_id=user_id,
                lecture_id=SAMPLE_LECTURE_ID,
                knowledge_point_id=point_id,
                kind="single",
                stem="昨天没做的题，今天要怎么处理？",
                options_json=json.dumps(
                    [
                        {"id": "A", "text": "全部堆到今天"},
                        {"id": "B", "text": "不堆过来，今天仍最多三件"},
                    ],
                    ensure_ascii=False,
                ),
                answer="B",
                analysis="没做的不堆到今天。",
                source_json=json.dumps({"page": 2}, ensure_ascii=False),
                difficulty="easy",
            )
        )
        session.add(PlanDay(id=plan_id, user_id=user_id, day=day, intensity="normal"))
        tasks = [
            ("learn", "交第 6 讲课件", "课件交上来", 1),
            ("practice", "第 6 讲做 2 道题", "做完一组题", 2),
            ("repair", "看看还没掌握的那一点", "看完要点", 3),
        ]
        for kind, title, done_when, order in tasks:
            session.add(
                PlanTask(
                    id=_sid(user_id, f"task-{kind}"),
                    user_id=user_id,
                    plan_day_id=plan_id,
                    day=day,
                    kind=kind,
                    title=title,
                    ref_json=json.dumps({"lecture_id": SAMPLE_LECTURE_ID}, ensure_ascii=False),
                    done_when=done_when,
                    status="todo",
                    sort_order=order,
                )
            )
        session.add(
            AgentAction(
                id=_sid(user_id, "suggest-1"),
                user_id=user_id,
                trigger="用户说今天时间少（样例，尚未发生）",
                suggestion_json=json.dumps(
                    {
                        "title": "今天换成轻松",
                        "body": "还是三件，每件少一点，大约 15 分钟。",
                        "label": "模拟",
                    },
                    ensure_ascii=False,
                ),
                status="pending",
                before_json=json.dumps({"intensity": "normal"}, ensure_ascii=False),
                after_json=json.dumps({"intensity": "light"}, ensure_ascii=False),
                created_at=_now(),
            )
        )
        session.add(
            StudyMessage(
                id=_sid(user_id, "msg-1"),
                user_id=user_id,
                role="assistant",
                content="我是小满。地基阶段先用样例和你打个招呼，今天的三件在左边。",
                refs_json="[]",
                feedback="",
                created_at=_now(),
            )
        )
        session.add(
            StudyEvent(
                id=_sid(user_id, "evt-seed"),
                user_id=user_id,
                name="foundation_seed",
                at=_now(),
                props_json=json.dumps({"mock": True}, ensure_ascii=False),
            )
        )
        session.add(UserSetting(user_id=user_id, permissions_json="{}", permissions_chosen=0))
        session.commit()


def _loads(raw: str, default: Any) -> Any:
    try:
        return json.loads(raw or "")
    except json.JSONDecodeError:
        return default


def _task_dict(row: PlanTask) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "kind_label": KIND_LABEL.get(row.kind, row.kind),
        "title": row.title,
        "status": row.status,
        "done_when": row.done_when,
        "ref": _loads(row.ref_json, {}),
    }


def _latest_plan(session, user_id: str) -> Optional[PlanDay]:
    rows = session.scalars(select(PlanDay).where(PlanDay.user_id == user_id)).all()
    if not rows:
        return None
    day = today_str()
    for row in rows:
        if row.day == day:
            return row
    return sorted(rows, key=lambda item: item.day)[-1]


def plan_today(user_id: str) -> dict[str, Any]:
    seed(user_id)
    with SessionLocal() as session:
        plan = _latest_plan(session, user_id)
        assert plan is not None
        tasks = session.scalars(
            select(PlanTask)
            .where(PlanTask.user_id == user_id, PlanTask.plan_day_id == plan.id)
            .order_by(PlanTask.sort_order)
        ).all()
        label, minutes = INTENSITY.get(plan.intensity, INTENSITY["normal"])
        return {
            "date": plan.day,
            "intensity": plan.intensity,
            "intensity_label": label,
            "minutes": minutes,
            "tasks": [_task_dict(task) for task in tasks],
            "label": "模拟",
        }


def patch_task(user_id: str, task_id: str, *, status: Optional[str] = None) -> Optional[dict[str, Any]]:
    seed(user_id)
    if status is not None and status not in ("todo", "done"):
        raise ValueError("status 只能是 todo 或 done")
    with SessionLocal() as session:
        row = session.get(PlanTask, task_id)
        if row is None or row.user_id != user_id:
            return None
        if status is not None:
            row.status = status
            session.add(
                StudyEvent(
                    id=uuid.uuid4().hex,
                    user_id=user_id,
                    name="task_status",
                    at=_now(),
                    props_json=json.dumps({"task_id": task_id, "status": status}, ensure_ascii=False),
                )
            )
        session.commit()
        session.refresh(row)
        return _task_dict(row)


def set_intensity(user_id: str, intensity: str) -> dict[str, Any]:
    if intensity not in INTENSITY:
        raise ValueError("intensity 只能是 light、normal 或 sprint")
    seed(user_id)
    with SessionLocal() as session:
        plan = _latest_plan(session, user_id)
        assert plan is not None
        plan.intensity = intensity
        session.commit()
    return plan_today(user_id)


def goals_current(user_id: str) -> dict[str, Any]:
    seed(user_id)
    with SessionLocal() as session:
        row = session.scalar(select(Goal).where(Goal.user_id == user_id))
        assert row is not None
        return _goal_dict(row)


def save_goal(user_id: str, *, title: str, exam_date: str, lecture_count: int, daily_minutes: int) -> dict[str, Any]:
    seed(user_id)
    with SessionLocal() as session:
        row = session.scalar(select(Goal).where(Goal.user_id == user_id))
        assert row is not None
        row.title = (title or row.title)[:200]
        row.exam_date = (exam_date or "")[:32]
        if lecture_count > 0:
            row.lecture_count = lecture_count
        if daily_minutes > 0:
            row.daily_minutes = daily_minutes
        row.status = "active"
        row.summary_json = json.dumps(
            {
                "phases": ["按讲推进", "每天最多三件", "考前复习"],
                "label": "模拟",
                "exam_date": row.exam_date,
                "lecture_count": row.lecture_count,
                "daily_minutes": row.daily_minutes,
            },
            ensure_ascii=False,
        )
        session.commit()
        session.refresh(row)
        return _goal_dict(row)


def _goal_dict(row: Goal) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "exam_date": row.exam_date,
        "status": row.status,
        "lecture_count": row.lecture_count,
        "daily_minutes": row.daily_minutes,
        "summary": _loads(row.summary_json, {}),
        "card_type": "goal",
        "label": "模拟",
    }


def list_notes(user_id: str) -> list[dict[str, Any]]:
    seed(user_id)
    with SessionLocal() as session:
        rows = session.scalars(select(Note).where(Note.user_id == user_id)).all()
        return [_note_dict(row, brief=True) for row in rows]


def get_note(user_id: str, note_id: str) -> Optional[dict[str, Any]]:
    seed(user_id)
    with SessionLocal() as session:
        row = session.get(Note, note_id)
        if row is None or row.user_id != user_id:
            return None
        return _note_dict(row, brief=False)


def patch_note(user_id: str, note_id: str, content: dict[str, Any]) -> Optional[dict[str, Any]]:
    seed(user_id)
    with SessionLocal() as session:
        row = session.get(Note, note_id)
        if row is None or row.user_id != user_id:
            return None
        row.content_json = json.dumps(content, ensure_ascii=False)[:20000]
        row.edited_by_user = 1
        session.commit()
        session.refresh(row)
        return _note_dict(row, brief=False)


def _note_dict(row: Note, *, brief: bool) -> dict[str, Any]:
    content = _loads(row.content_json, {})
    data = {
        "id": row.id,
        "lecture_id": row.lecture_id,
        "title": row.title,
        "edited_by_user": bool(row.edited_by_user),
        "label": "AI 整理，可以改",
    }
    if brief:
        points = content.get("points") if isinstance(content, dict) else None
        data["point_count"] = len(points) if isinstance(points, list) else 0
        return data
    data["content"] = content
    return data


def file_status(user_id: str, file_id: str) -> Optional[dict[str, Any]]:
    seed(user_id)
    with SessionLocal() as session:
        row = session.get(StudyFile, file_id)
        if row is None or row.user_id != user_id:
            return None
        kb = session.scalar(select(KbDocument).where(KbDocument.user_id == user_id, KbDocument.file_id == file_id))
        return {
            "id": row.id,
            "filename": row.filename,
            "parse_status": row.parse_status,
            "kb_status": kb.status if kb else "",
            "lecture_id": row.lecture_id,
            "mock": True,
        }


def create_upload(user_id: str, filename: str, mime: str) -> dict[str, Any]:
    seed(user_id)
    file_id = uuid.uuid4().hex
    with SessionLocal() as session:
        session.add(
            StudyFile(
                id=file_id,
                user_id=user_id,
                filename=(filename or "未命名.pdf")[:200],
                mime=(mime or "application/pdf")[:128],
                storage_path=f"local://{file_id}",
                parse_status="awaiting_upload",
                lecture_id="",
                created_at=_now(),
            )
        )
        session.commit()
    return {
        "file_id": file_id,
        "upload_url": f"/api/files/{file_id}/raw",
        "method": "PUT",
        "headers": {},
        "expires_in": 600,
        "mock": True,
    }


def mark_uploaded(user_id: str, file_id: str) -> bool:
    with SessionLocal() as session:
        row = session.get(StudyFile, file_id)
        if row is None or row.user_id != user_id:
            return False
        if row.parse_status == "awaiting_upload":
            row.parse_status = "uploaded"
        session.commit()
    return True


def complete_file(user_id: str, file_id: str, lecture_id: str) -> Optional[dict[str, Any]]:
    seed(user_id)
    lecture = (lecture_id or SAMPLE_LECTURE_ID).strip() or SAMPLE_LECTURE_ID
    with SessionLocal() as session:
        row = session.get(StudyFile, file_id)
        if row is None or row.user_id != user_id:
            return None
        row.parse_status = "ready"
        row.lecture_id = lecture
        kb = session.scalar(select(KbDocument).where(KbDocument.user_id == user_id, KbDocument.file_id == file_id))
        if kb is None:
            session.add(KbDocument(id=uuid.uuid4().hex, user_id=user_id, file_id=file_id, status="ready"))
        else:
            kb.status = "ready"
        existing_pages = session.scalars(
            select(MaterialPage).where(MaterialPage.user_id == user_id, MaterialPage.file_id == file_id)
        ).all()
        if not existing_pages:
            for item in SAMPLE_PAGES:
                session.add(
                    MaterialPage(
                        id=uuid.uuid4().hex,
                        user_id=user_id,
                        lecture_id=lecture,
                        file_id=file_id,
                        page_no=item["page"],
                        text=item["text"],
                    )
                )
        session.commit()
    return file_status(user_id, file_id)


def make_quiz(user_id: str, lecture_id: str, count: int) -> dict[str, Any]:
    seed(user_id)
    lecture = (lecture_id or SAMPLE_LECTURE_ID).strip() or SAMPLE_LECTURE_ID
    with SessionLocal() as session:
        rows = session.scalars(
            select(Question).where(Question.user_id == user_id, Question.lecture_id == lecture)
        ).all()
        if not rows:
            rows = session.scalars(select(Question).where(Question.user_id == user_id)).all()
        picked = list(rows)[: max(1, min(count or 2, 5))]
        return {
            "lecture_id": lecture,
            "label": "模拟",
            "questions": [
                {
                    "id": row.id,
                    "kind": row.kind,
                    "stem": row.stem,
                    "options": _loads(row.options_json, []),
                    "difficulty": row.difficulty,
                    "knowledge_point_id": row.knowledge_point_id,
                }
                for row in picked
            ],
        }


def grade_attempt(
    user_id: str,
    *,
    question_id: str,
    answer: str,
    seconds: int,
    confidence: str,
) -> Optional[dict[str, Any]]:
    seed(user_id)
    with SessionLocal() as session:
        question = session.get(Question, question_id)
        if question is None or question.user_id != user_id:
            return None
        correct = (answer or "").strip() == question.answer
        attempt = Attempt(
            id=uuid.uuid4().hex,
            user_id=user_id,
            question_id=question_id,
            answer=(answer or "")[:500],
            correct=1 if correct else 0,
            score=1 if correct else 0,
            seconds=max(0, seconds),
            confidence=(confidence or "")[:16],
            created_at=_now(),
        )
        session.add(attempt)
        session.commit()
        return {
            "attempt_id": attempt.id,
            "question_id": question_id,
            "correct": correct,
            "score": attempt.score,
            "answer": question.answer,
            "analysis": question.analysis,
            "source": _loads(question.source_json, {}),
            "label": "模拟",
        }


def list_mistakes(user_id: str) -> dict[str, Any]:
    seed(user_id)
    with SessionLocal() as session:
        wrong = session.scalars(
            select(Attempt).where(Attempt.user_id == user_id, Attempt.correct == 0)
        ).all()
        items = []
        for row in wrong:
            question = session.get(Question, row.question_id)
            if question is None:
                continue
            items.append(
                {
                    "attempt_id": row.id,
                    "question_id": question.id,
                    "stem": question.stem,
                    "your_answer": row.answer,
                    "answer": question.answer,
                    "lecture_id": question.lecture_id,
                }
            )
        return {"items": items, "label": "模拟"}


def list_suggestions(user_id: str) -> dict[str, Any]:
    seed(user_id)
    with SessionLocal() as session:
        rows = session.scalars(select(AgentAction).where(AgentAction.user_id == user_id)).all()
        return {"items": [_action_dict(row) for row in rows], "label": "模拟"}


def _action_dict(row: AgentAction) -> dict[str, Any]:
    return {
        "id": row.id,
        "trigger": row.trigger,
        "suggestion": _loads(row.suggestion_json, {}),
        "status": row.status,
        "before": _loads(row.before_json, {}),
        "after": _loads(row.after_json, {}),
    }


def accept_suggestion(user_id: str, action_id: str) -> Optional[dict[str, Any]]:
    seed(user_id)
    with SessionLocal() as session:
        row = session.get(AgentAction, action_id)
        if row is None or row.user_id != user_id:
            return None
        after = _loads(row.after_json, {})
        row.status = "executed"
        intensity = after.get("intensity")
        if intensity in INTENSITY:
            plan = _latest_plan(session, user_id)
            if plan is not None:
                plan.intensity = intensity
        session.commit()
        session.refresh(row)
        data = _action_dict(row)
    data["plan"] = plan_today(user_id)
    return data


def undo_action(user_id: str, action_id: str) -> Optional[dict[str, Any]]:
    seed(user_id)
    with SessionLocal() as session:
        row = session.get(AgentAction, action_id)
        if row is None or row.user_id != user_id:
            return None
        before = _loads(row.before_json, {})
        row.status = "undone"
        intensity = before.get("intensity")
        if intensity in INTENSITY:
            plan = _latest_plan(session, user_id)
            if plan is not None:
                plan.intensity = intensity
        session.commit()
        session.refresh(row)
        data = _action_dict(row)
    data["plan"] = plan_today(user_id)
    return data


def permissions(user_id: str) -> dict[str, Any]:
    seed(user_id)
    with SessionLocal() as session:
        row = session.get(UserSetting, user_id)
        assert row is not None
        return {
            "permissions": _loads(row.permissions_json, {}),
            "chosen": bool(row.permissions_chosen),
            "note": "默认值不算用户的选择。还没点过时 chosen 为 false。",
        }


def patch_permissions(user_id: str, permissions_payload: dict[str, Any]) -> dict[str, Any]:
    seed(user_id)
    with SessionLocal() as session:
        row = session.get(UserSetting, user_id)
        assert row is not None
        row.permissions_json = json.dumps(permissions_payload, ensure_ascii=False)[:4000]
        row.permissions_chosen = 1
        session.commit()
    return permissions(user_id)


def dashboard(user_id: str, range_name: str) -> dict[str, Any]:
    seed(user_id)
    with SessionLocal() as session:
        attempts = session.scalars(select(Attempt).where(Attempt.user_id == user_id)).all()
        mistakes = [row for row in attempts if not row.correct]
        points = session.scalars(select(KnowledgePoint).where(KnowledgePoint.user_id == user_id)).all()
        goal = session.scalar(select(Goal).where(Goal.user_id == user_id))
        files = session.scalars(select(StudyFile).where(StudyFile.user_id == user_id)).all()
        chapters = session.scalars(select(Chapter).where(Chapter.user_id == user_id)).all()
        calls = session.scalars(select(LlmCall).where(LlmCall.user_id == user_id)).all()
        return {
            "range": range_name or "week",
            "studied_days": 1,
            "attempt_count": len(attempts),
            "mistakes_due": len(mistakes),
            "lectures": [
                {
                    "id": chapter.lecture_id,
                    "title": chapter.title,
                    "mastery": next((point.mastery for point in points if point.lecture_id == chapter.lecture_id), 0),
                }
                for chapter in chapters
            ],
            "files": [
                {"id": row.id, "filename": row.filename, "parse_status": row.parse_status}
                for row in files
            ],
            "goal_progress": 0.2 if goal is not None else 0,
            "llm_calls": len(calls),
            "label": "模拟",
            "note": "只和自己的过去比。",
        }


def usage_for(user_id: str) -> dict[str, Any]:
    ensure_schema()
    with SessionLocal() as session:
        rows = session.scalars(select(LlmCall).where(LlmCall.user_id == user_id)).all()
        by_cap: dict[str, dict[str, int]] = {}
        items = []
        for row in rows:
            bucket = by_cap.setdefault(
                row.capability, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
            )
            bucket["calls"] += 1
            bucket["prompt_tokens"] += row.prompt_tokens
            bucket["completion_tokens"] += row.completion_tokens
            items.append(
                {
                    "id": row.id,
                    "capability": row.capability,
                    "prompt": f"{row.prompt_name}@{row.prompt_version}",
                    "model": row.model,
                    "prompt_tokens": row.prompt_tokens,
                    "completion_tokens": row.completion_tokens,
                    "ok": bool(row.ok),
                    "estimated": bool(row.estimated),
                    "created_at": row.created_at,
                }
            )
        return {"items": items[-20:], "by_capability": by_cap}


def bad_cases_for(user_id: str) -> dict[str, Any]:
    ensure_schema()
    with SessionLocal() as session:
        rows = session.scalars(select(BadCase).where(BadCase.user_id == user_id)).all()
        return {
            "items": [
                {
                    "id": row.id,
                    "capability": row.capability,
                    "problem_type": row.problem_type,
                    "severity": row.severity,
                    "status": row.status,
                    "source": row.source,
                    "model": row.model,
                    "prompt_version": row.prompt_version,
                    "actual_output": row.actual_output,
                    "expected_output": row.expected_output,
                    "fix_note": row.fix_note,
                    "created_at": row.created_at,
                }
                for row in rows
            ]
        }
