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


@pytest.mark.parametrize("minutes,expected", [
    (40, "每天 40 分钟——我先按「正常」排，每天约 30 分钟；想多学点，可以在「今天」里改成「冲刺」（约 50 分钟）。"),
    (20, "每天 20 分钟——我先按「轻松」排，每天约 15 分钟；想多学点，可以在「今天」里改成「正常」（约 30 分钟）。"),
    (25, "每天 25 分钟——我先按「正常」排，每天约 30 分钟；时间不够的那天，做完一部分也算。"),
    (90, "每天 90 分钟——我先按「冲刺」排，每天约 50 分钟，这是最多的一档。"),
])
def test_minutes_not_matching_a_tier_are_explained(minutes, expected):
    assert g.minutes_note(minutes) == expected


@pytest.mark.parametrize("minutes", [15, 30, 50, None])
def test_exact_tiers_need_no_note(minutes):
    assert g.minutes_note(minutes) == ""


def test_tiers_match_outline_service():
    # 和 v2.service 定档规则一致（≤20 轻松 / ≤40 正常 / 其余冲刺）
    assert [g.tier_for(m)[0] for m in (5, 20, 21, 40, 41, 300)] == ["轻松", "轻松", "正常", "正常", "冲刺", "冲刺"]


def test_opening_ack_includes_tier_note():
    ack = g._ack(g.prefill("我想一个月后学会 Python，每天 40 分钟", "u"))
    assert ack.startswith("好，记下了：") and "按「正常」排" in ack
