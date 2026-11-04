"""技术主文档里的学习表。每张表都有 user_id。

用户档案沿用底座 ``user_profiles``，不另建 users。
对话主链路仍在底座；这里的 ``messages`` 是学习侧留档，给以后的问答线用。
``llm_calls`` 是按用户、按能力落库的用量。底座另有内存里的用量环，没有 user_id。
``kb_documents`` 先单独建。要不要并进 ``files`` 由 A 决定，见 schema.sql 顶部说明。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    exam_date: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(16), default="active")  # active / paused / done
    lecture_count: Mapped[int] = mapped_column(Integer, default=0)
    daily_minutes: Mapped[int] = mapped_column(Integer, default=30)
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(String(40), default=_now)


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    goal_id: Mapped[str] = mapped_column(String(200), default="")
    title: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    course_id: Mapped[str] = mapped_column(String(200), default="")
    title: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    lecture_id: Mapped[str] = mapped_column(String(200), default="")


class StudyFile(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    filename: Mapped[str] = mapped_column(Text, default="")
    mime: Mapped[str] = mapped_column(String(128), default="application/pdf")
    storage_path: Mapped[str] = mapped_column(Text, default="")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    parse_status: Mapped[str] = mapped_column(String(32), default="awaiting_upload")
    lecture_id: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[str] = mapped_column(String(40), default=_now)


class KbDocument(Base):
    """资料处理记录。暂不并进 files。见 docs/地基给各线.md。"""

    __tablename__ = "kb_documents"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    file_id: Mapped[str] = mapped_column(String(200), index=True)
    status: Mapped[str] = mapped_column(String(16), default="reading")  # reading / ready / failed


class MaterialPage(Base):
    """资料页：哪一讲、第几页、文字。取资料内容读这张表。"""

    __tablename__ = "material_pages"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    lecture_id: Mapped[str] = mapped_column(String(200), index=True)
    file_id: Mapped[str] = mapped_column(String(200), default="")
    page_no: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, default="")


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    lecture_id: Mapped[str] = mapped_column(String(200), default="")
    title: Mapped[str] = mapped_column(Text, default="")
    content_json: Mapped[str] = mapped_column(Text, default="{}")
    edited_by_user: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(40), default=_now)


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    lecture_id: Mapped[str] = mapped_column(String(200), default="")
    name: Mapped[str] = mapped_column(Text, default="")
    explanation: Mapped[str] = mapped_column(Text, default="")
    source_json: Mapped[str] = mapped_column(Text, default="{}")
    mastery: Mapped[int] = mapped_column(Integer, default=0)
    next_review_on: Mapped[str] = mapped_column(String(32), default="")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    lecture_id: Mapped[str] = mapped_column(String(200), default="")
    knowledge_point_id: Mapped[str] = mapped_column(String(200), default="")
    kind: Mapped[str] = mapped_column(String(32), default="single")
    stem: Mapped[str] = mapped_column(Text, default="")
    options_json: Mapped[str] = mapped_column(Text, default="[]")
    answer: Mapped[str] = mapped_column(Text, default="")
    analysis: Mapped[str] = mapped_column(Text, default="")
    source_json: Mapped[str] = mapped_column(Text, default="{}")
    difficulty: Mapped[str] = mapped_column(String(16), default="easy")


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    question_id: Mapped[str] = mapped_column(String(200), index=True)
    answer: Mapped[str] = mapped_column(Text, default="")
    correct: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[int] = mapped_column(Integer, default=0)
    seconds: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[str] = mapped_column(String(16), default="")
    created_at: Mapped[str] = mapped_column(String(40), default=_now)


class PlanDay(Base):
    __tablename__ = "plan_days"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    day: Mapped[str] = mapped_column(String(32), index=True)
    intensity: Mapped[str] = mapped_column(String(16), default="normal")  # light / normal / sprint


class PlanTask(Base):
    __tablename__ = "plan_tasks"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    plan_day_id: Mapped[str] = mapped_column(String(200), default="")
    day: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # learn / practice / repair
    title: Mapped[str] = mapped_column(Text, default="")
    ref_json: Mapped[str] = mapped_column(Text, default="{}")
    done_when: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="todo")  # todo / done
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class AgentAction(Base):
    __tablename__ = "agent_actions"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    trigger: Mapped[str] = mapped_column(Text, default="")
    suggestion_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending / executed / undone
    before_json: Mapped[str] = mapped_column(Text, default="{}")
    after_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(String(40), default=_now)


class StudyMessage(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    role: Mapped[str] = mapped_column(String(16), default="assistant")
    content: Mapped[str] = mapped_column(Text, default="")
    refs_json: Mapped[str] = mapped_column(Text, default="[]")
    feedback: Mapped[str] = mapped_column(String(8), default="")  # up / down / 空
    created_at: Mapped[str] = mapped_column(String(40), default=_now)


class StudyEvent(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(64))
    at: Mapped[str] = mapped_column(String(40), default=_now)
    props_json: Mapped[str] = mapped_column(Text, default="{}")


class LlmCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    capability: Mapped[str] = mapped_column(String(64), index=True)
    prompt_name: Mapped[str] = mapped_column(String(64), default="")
    prompt_version: Mapped[str] = mapped_column(String(16), default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[int] = mapped_column(Integer, default=1)
    estimated: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[str] = mapped_column(String(40), default=_now)


class BadCase(Base):
    """字段对齐 PRD「Bad case 库与数据飞轮」。"""

    __tablename__ = "bad_cases"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    capability: Mapped[str] = mapped_column(String(64), index=True)
    input_json: Mapped[str] = mapped_column(Text, default="{}")
    actual_output: Mapped[str] = mapped_column(Text, default="")
    expected_output: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    problem_type: Mapped[str] = mapped_column(String(32), default="")
    severity: Mapped[str] = mapped_column(String(8), default="低")  # 高 / 中 / 低
    status: Mapped[str] = mapped_column(String(16), default="新")
    owner: Mapped[str] = mapped_column(String(64), default="")
    fix_note: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(32), default="backend")
    created_at: Mapped[str] = mapped_column(String(40), default=_now)


class UserSetting(Base):
    """授权开关。合同写在档案上，地基先单独放，避免改底座 profile 结构。"""

    __tablename__ = "user_settings"

    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    permissions_json: Mapped[str] = mapped_column(Text, default="{}")
    permissions_chosen: Mapped[int] = mapped_column(Integer, default=0)
