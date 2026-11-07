"""定目标对话：开口那句话里说过的完成时间 / 每天时间不再重复问；“半小时”这类说法能听懂。"""
from datetime import date

import pytest

from app.study.v2 import goal_flow as g


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(g.plan_service, "today_for", lambda user_id: date(2026, 11, 8))


@pytest.mark.parametrize("text,deadline,minutes", [
    ("我想两周后考过 PMP，每天能学半小时", "2026-11-22", 30),
    ("三个月内学会 Python，每天 1 小时", "2027-02-06", 60),
    ("12月底前，每天一个半小时", "2026-12-28", 90),
    ("20天，45分钟", "2026-11-28", 45),
    ("下个月考试，每天两小时", "2026-12-08", 120),
])
def test_prefill_reads_deadline_and_minutes(text, deadline, minutes):
    found = g.prefill(text, "u")
    assert found["deadline"] == deadline
    assert found["daily_minutes"] == minutes


def test_prefill_ignores_what_was_not_said():
    assert g.prefill("我想学吉他", "u") == {}
    assert g.prefill("零基础学吉他", "u") == {"progress": "刚开始"}


@pytest.mark.parametrize("text,value", [("半小时", 30), ("1小时", 60), ("二十分钟", 20), ("30", 30), ("一刻钟", 15)])
def test_minutes_answers(text, value):
    assert g._parse_minutes(text) == value


@pytest.mark.parametrize("text,value", [("没有", "none"), ("没有资料", "none"), ("有的，晚点交吧", "later"), ("有，现在交", "now")])
def test_materials_answers(text, value):
    assert g._parse_materials(text) == value


def test_next_step_skips_answered():
    p = {"deadline_text": "两周", "daily_minutes": 30, "materials_known": False, "progress": ""}
    assert g._next_step(p) == "materials"
    p["materials_known"] = True
    assert g._next_step(p) == "progress"
    p["progress"] = "刚开始"
    assert g._next_step(p) == "done"


def test_old_pending_state_does_not_go_back():
    # 改版前存下的进行中状态没有 materials_known，已经走到“进度”这一步时不能退回去问资料。
    p = {"deadline_text": "不急", "daily_minutes": 30, "progress": "", "step": "progress"}
    assert g._next_step(p) == "progress"


def test_retry_question_explains_how_to_answer():
    q = g._question("minutes", retry=True)
    assert "半小时" in q["question"] and q["options"] == g.QUESTIONS["minutes"]["options"]
    assert g.QUESTIONS["minutes"]["question"] == "每天大概有多少时间？"  # 原题不被改写
