"""V2 学习大纲和阶段测验；JSON 与时间沿用学习表的文本格式。"""
from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.study.common.models import _now


class GoalOutline(Base):
    __tablename__ = "goal_outlines"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    goal_id: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft / accepted / replaced
    goal_type: Mapped[str] = mapped_column(String(16), default="exam")  # exam / course / skill
    title: Mapped[str] = mapped_column(Text, default="")
    units_json: Mapped[str] = mapped_column(Text, default="[]")
    stages_json: Mapped[str] = mapped_column(Text, default="[]")
    label: Mapped[str] = mapped_column(String(64), default="AI 整理，可以改")
    created_at: Mapped[str] = mapped_column(String(40), default=_now)
    updated_at: Mapped[str] = mapped_column(String(40), default=_now)


class Assessment(Base):
    __tablename__ = "assessments"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    outline_id: Mapped[str] = mapped_column(String(200))
    stage_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open / submitted
    question_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    report_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(String(40), default=_now)
    submitted_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class UnitLecture(Base):
    __tablename__ = "unit_lectures"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    outline_id: Mapped[str] = mapped_column(String(200))
    unit_no: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text, default="")
    sections_json: Mapped[str] = mapped_column(Text, default="[]")
    label: Mapped[str] = mapped_column(String(64), default="通用知识，没有出处")
    created_at: Mapped[str] = mapped_column(String(40), default=_now)
