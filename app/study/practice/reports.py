"""用户反馈的有效状态与审计历史；和统计更新在同一数据库事务中提交。"""
from sqlalchemy import select
from app.data_access.session import SessionLocal

from app.study.common.models import Attempt, BadCase, StudyEvent, StudyFile, _now
from app.study.practice import learning, service
from app.study.practice.capabilities import PracticeError


def get_report(uid, qid):
    service.ensure_schema()
    with SessionLocal() as session:
        if service.question(session, uid, qid) is None:
            raise LookupError()
        return learning.feedback_records(session, uid).get(qid, {"question_id": qid, "active": False, "storage": "server"})


def save_report(uid, qid, reason, category, quiz_id="", current_attempt_id=""):
    return _change(uid, qid, reason, category, quiz_id, current_attempt_id, False)


def withdraw_report(uid, qid):
    return _change(uid, qid, "", None, "", "", True)


def _change(uid, qid, reason, category, quiz_id, current_attempt_id, withdraw):
    service.ensure_schema()
    with service.lock_for(uid), SessionLocal() as session:
        q = service.question(session, uid, qid)
        if q is None:
            raise LookupError()
        previous = learning.feedback_records(session, uid).get(qid, {})
        if not withdraw and category not in learning.REPORT_LABELS:
            raise PracticeError("请至少选择一种问题类型")
        if quiz_id:
            quiz = service.quiz_record(session, uid, quiz_id)
            if qid not in quiz["question_ids"]:
                raise LookupError()
            current_attempt_id = service.attempt_id(quiz_id, qid)
        attempt = session.scalar(select(Attempt).where(Attempt.user_id == uid, Attempt.question_id == qid,
                                Attempt.id == current_attempt_id)) if current_attempt_id else session.scalar(
            select(Attempt).where(Attempt.user_id == uid, Attempt.question_id == qid).order_by(Attempt.created_at.desc(), Attempt.id.desc()))
        if current_attempt_id and not attempt and not quiz_id:
            raise LookupError()
        from app.agent.harness.redact import redact_text
        reason = redact_text(reason.strip(), max_len=1000)
        pdf = session.scalar(select(StudyFile).where(StudyFile.user_id == uid, StudyFile.lecture_id == q.lecture_id))
        now = _now()
        eid = "pf-" + service.digest([uid, qid])[:40]
        row = session.scalar(select(StudyEvent).where(StudyEvent.user_id == uid, StudyEvent.id == eid))
        history = list(previous.get("history", []))
        if previous:
            history.append({k: v for k, v in previous.items() if k not in ("history", "message")})
        record = {**previous, "question_id": qid, "lecture_id": q.lecture_id, "pdf_source": service.source(q),
                  "file_id": pdf.id if pdf else "", "pdf_sha256": pdf.sha256 if pdf else "",
                  "root_id": service.root(q), "active": not withdraw, "storage": "server",
                  "created_at": previous.get("created_at", now), "updated_at": now, "history": history}
        if not withdraw:
            record.update(category=category, category_label=learning.REPORT_LABELS[category], reason=reason.strip(),
                          quiz_id=quiz_id or previous.get("quiz_id", ""), attempt_id=attempt.id if attempt else "")
            record["message"] = learning.REPORT_SUCCESS
        else:
            record["message"] = "已撤回反馈，本题已恢复参与学习统计。"
        # 保留与现有 bad case 库的衔接，但不模拟审核或修改公共答案。
        bid = previous.get("bad_case_id") or "pb-" + service.digest([uid, qid])[:40]
        case = session.scalar(select(BadCase).where(BadCase.user_id == uid, BadCase.id == bid))
        if case is None:
            case = BadCase(id=bid, user_id=uid, capability="practice", source="question_feedback", actual_output="用户反馈，未经确认")
            session.add(case)
        record["bad_case_id"] = bid
        case.input_json = service.dump({"question_id": qid, "lecture_id": q.lecture_id, "attempt_id": record.get("attempt_id", ""),
                                       "quiz_id": record.get("quiz_id", ""), "category": record.get("category"), "active": not withdraw})
        case.fix_note = record.get("reason", "")
        case.problem_type = record.get("category_label", "用户反馈")
        if row is None:
            row = StudyEvent(id=eid, user_id=uid, name="practice_question_feedback")
            session.add(row)
        row.props_json = service.dump(record)
        session.flush()
        service.recompute_learning(session, uid)
        session.commit()
        return record
