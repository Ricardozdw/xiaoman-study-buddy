"""学习状态、反馈状态和统计的唯一规则入口；使用原有表，不更改历史作答。"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.study.common.models import Attempt, BadCase, Question, StudyEvent

REPORT_SUCCESS = '已记录你的反馈。本题已标记为“已反馈问题”，暂不计入学习统计，也不会进入推荐复习。'
REPORT_NOTE = '以上为当前题目答案的判定；你已反馈本题存在问题，本题暂不参与学习统计。'
REPORT_LABELS = {"answer": "答案或解析不对", "ambiguous": "题干或选项有歧义", "source": "出处对不上", "other": "其他问题"}
STATE_LABELS = {"wrong": "待巩固", "normal": "答对的题", "reported": "已反馈问题", "unanswered": "尚未作答"}
CONFIDENCE_LABELS = {"": "未标注", "low": "没有把握", "medium": "有点把握", "high": "很有把握"}


def metadata(q):
    return json.loads(q.source_json).get("practice", {})


def root(q):
    return metadata(q).get("original_id") or q.id


def confidence_info(raw):
    # 仅映射已知存储值；不把任意历史文本猜成低把握，也不改写原值。
    raw = "" if raw is None else raw
    known = raw in CONFIDENCE_LABELS
    return {"confidence": raw, "confidence_status": ("unmarked" if raw == "" else raw) if known else "legacy_unknown",
            "confidence_label": CONFIDENCE_LABELS.get(raw, f"历史把握度：{raw}（未映射）")}


def classification(correct, confidence="", *, excluded=False, practiced=False):
    # confidence 仅为旧调用保留参数；新旧记录一律只根据对错分类，不改写历史原值。
    if excluded:
        return {"learning_state": "reported", "learning_label": STATE_LABELS["reported"], "priority": False,
                "review_recommended": False, "review_rank": None, "excluded": True, "review_passed": False}
    state = "normal" if correct else "wrong"
    return {"learning_state": state, "learning_label": STATE_LABELS[state], "priority": False,
            "review_recommended": not correct, "review_rank": None if correct else 0,
            "excluded": False, "review_passed": bool(practiced and correct)}


def action_feedback(correct, confidence="", excluded=False):
    # 对错及解析由结果主体显示，移除旧的把握度行动提示。
    return REPORT_NOTE if excluded else ""


def feedback_records(session, uid):
    records = {}
    # 兼容此前仅写进 bad_cases 的真实服务端反馈。原记录全部保留。
    old = session.scalars(select(BadCase).where(BadCase.user_id == uid, BadCase.source == "question_feedback")
                          .order_by(BadCase.created_at, BadCase.id)).all()
    for case in old:
        data = json.loads(case.input_json)
        qid = data.get("question_id")
        if not qid:
            continue
        raw_category = data.get("category", "other")
        category = raw_category if raw_category in REPORT_LABELS else "other"
        previous = records.get(qid, {})
        history = previous.get("legacy_history", []) + [{"id": case.id, "input": data, "reason": case.fix_note, "created_at": case.created_at}]
        records[qid] = {"question_id": qid, "active": True, "category": category, "category_raw": raw_category,
                        "category_label": REPORT_LABELS[category], "reason": case.fix_note,
                        "created_at": previous.get("created_at", case.created_at), "updated_at": case.created_at,
                        "attempt_id": data.get("attempt_id", ""), "quiz_id": data.get("quiz_id", ""),
                        "lecture_id": data.get("lecture_id", ""), "bad_case_id": case.id, "legacy_history": history,
                        "storage": "server", "message": REPORT_SUCCESS}
    rows = session.scalars(select(StudyEvent).where(StudyEvent.user_id == uid,
                                                   StudyEvent.name == "practice_question_feedback")).all()
    for row in rows:
        data = json.loads(row.props_json)
        records[data["question_id"]] = data  # 撤回的 tombstone 也覆盖旧 bad case，不能把旧反馈重新激活。
    return records


def snapshot(session, uid):
    qs = {q.id: q for q in session.scalars(select(Question).where(Question.user_id == uid)).all()}
    attempts = session.scalars(select(Attempt).where(Attempt.user_id == uid).order_by(Attempt.created_at, Attempt.id)).all()
    reports = feedback_records(session, uid)
    excluded_roots = {root(qs[qid]) for qid, report in reports.items() if report.get("active") and qid in qs}
    histories = defaultdict(list)
    representatives = {}
    for q in qs.values():
        rid = root(q)
        if rid not in representatives or q.id == rid:
            representatives[rid] = q
    for a in attempts:
        if a.question_id in qs:
            rid = root(qs[a.question_id])
            histories[rid].append(a)
            representatives[rid] = qs[a.question_id]
    items = []
    for rid, q in representatives.items():
        history = histories[rid]
        a = history[-1] if history else None
        active_reports = [r for qid, r in reports.items() if qid in qs and root(qs[qid]) == rid and r.get("active")]
        report = (active_reports[-1] if active_reports else reports.get(q.id))
        excluded = rid in excluded_roots
        state = classification(bool(a.correct), excluded=excluded, practiced=q.id != rid) if a else {
            "learning_state": "reported" if excluded else "unanswered", "learning_label": STATE_LABELS["reported" if excluded else "unanswered"],
            "priority": False, "review_recommended": False, "review_rank": None, "excluded": excluded, "review_passed": False}
        due = ""
        if a and state["review_recommended"]:
            dt = datetime.fromisoformat(a.created_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("UTC"))
            due = (dt.astimezone(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=1)).isoformat()
        items.append({"question": q, "attempt": a, "history": history, "root_id": rid, "report": report,
                      "next_review_on": due, **state})
    return {"questions": qs, "attempts": attempts, "reports": reports, "items": items, "excluded_roots": excluded_roots}


def summarize(items):
    valid = [item for item in items if item.get("has_attempt", item.get("attempt") is not None) and not item["excluded"]]
    correct = sum(bool(item.get("correct", bool(item["attempt"].correct) if item.get("attempt") else False)) for item in valid)
    def raw_confidence(item):
        return item.get("confidence", item["attempt"].confidence if item.get("attempt") else "")
    return {"effective_count": len(valid), "correct_count": correct,
            "accuracy": round(100 * correct / len(valid), 2) if valid else None,
            "wrong_count": len(valid) - correct,
            "consolidate_count": len(valid) - correct,  # 新“待巩固”即答错题，保留字段名兼容调用方。
            "reported_count": sum(item["excluded"] for item in items),
            "unmarked_count": sum(raw_confidence(item) in ("", None) for item in valid),
            "legacy_unknown_count": sum(confidence_info(raw_confidence(item))["confidence_status"] == "legacy_unknown" for item in valid)}
