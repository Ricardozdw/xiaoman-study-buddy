"""练习业务复用现有表，所有查询显式按 user_id 隔离。"""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.data_access.session import SessionLocal
from app.study.common.db import ensure_schema
from app.study.common.models import Attempt, BadCase, KnowledgePoint, PlanTask, Question, StudyEvent, _now
from app.study.materials.content import fetch_lecture_pages
from app.study.practice.capabilities import PROMPT_VERSIONS, PracticeError, generate
from app.study.practice.schemas import AttemptBody, ProgressBody, QuizBody
from app.study.practice import learning

_locks = [threading.RLock() for _ in range(64)]
def lock_for(user_id):
    return _locks[int(hashlib.sha256(user_id.encode()).hexdigest(), 16) % len(_locks)]


def today():
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def dump(value):
    return json.dumps(value, ensure_ascii=False)


def digest(value):
    return hashlib.sha256(dump(value).encode()).hexdigest()


def meta(q):
    return json.loads(q.source_json).get("practice", {})


def root(q):
    return meta(q).get("original_id") or q.id


def question(session, uid, qid):
    return session.scalar(select(Question).where(Question.id == qid, Question.user_id == uid))


def event(session, uid, name, payload, eid=""):
    session.add(StudyEvent(id=eid or uuid.uuid4().hex, user_id=uid, name=name, props_json=dump(payload)))


def quiz_record(session, uid, qid):
    row = session.scalar(select(StudyEvent).where(StudyEvent.id == qid, StudyEvent.user_id == uid,
                                                 StudyEvent.name == "practice_quiz_created"))
    if row is None:
        raise LookupError()
    return json.loads(row.props_json)


def attempt_id(quiz_id, qid):
    return "pa-" + digest([quiz_id, qid])[:40]


def source(q):
    return {k: v for k, v in json.loads(q.source_json).items() if k in ("page", "quote")}


def public(q):
    # 作答前不返回答案、解析、引用原句，避免泄题。
    return {"id": q.id, "kind": "single", "lecture_id": q.lecture_id, "stem": q.stem, "options": json.loads(q.options_json),
            "difficulty": q.difficulty, "knowledge_point_id": q.knowledge_point_id,
            "source": {"page": source(q).get("page")}, "mock": bool(meta(q).get("mock", True))}


def review_rows(session, uid, *, manual=False):
    # 主动勾选可练已答题；自动推荐仍只包含错题与待巩固。有效反馈始终排除。
    items = [item for item in learning.snapshot(session, uid)["items"]
             if item["attempt"] is not None and not item["excluded"] and (manual or item["review_recommended"])]
    items.sort(key=lambda item: (item["review_rank"] if item["review_rank"] is not None else 99,
                                 item["attempt"].created_at, item["root_id"]))
    return [(item["attempt"], item["question"]) for item in items]


def wrong_rows(session, uid):
    return [(a, q) for a, q in review_rows(session, uid) if not a.correct]


def validate_task(session, uid, task_id, lecture, mode):
    task = session.scalar(select(PlanTask).where(PlanTask.id == task_id, PlanTask.user_id == uid))
    if (not task or task.kind != ("repair" if mode == "review" else "practice")
            or json.loads(task.ref_json).get("lecture_id") != lecture):
        raise LookupError()
    return task


def create_quiz(uid: str, body: QuizBody):
    ensure_schema()
    with lock_for(uid):
        if body.mode == "review":
            with SessionLocal() as session:
                wrong = review_rows(session, uid, manual=bool(body.question_ids))
                available = {q.id for _, q in wrong} | {root(q) for _, q in wrong}
                if any(qid not in available for qid in body.question_ids):
                    raise LookupError()
                selected = [q for _, q in wrong if (q.id in body.question_ids or root(q) in body.question_ids)] if body.question_ids else [q for _, q in wrong if q.lecture_id == (body.lecture_id or "lec-6")]
                if body.question_ids and len(selected) > body.count:
                    raise PracticeError("所选题目超过本次题数，请调整选择")
                if not body.question_ids:
                    selected = selected[:body.count]
                if not selected:
                    raise PracticeError("这一讲暂时没有可推荐复习的题目")
                lecture = selected[0].lecture_id
                mixed = any(q.lecture_id != lecture for q in selected)
                if body.task_id:
                    if mixed:
                        raise PracticeError("关联今日任务时，请只选择该任务对应讲次的错题")
                    validate_task(session, uid, body.task_id, lecture, body.mode)
                selected_ids = [q.id for q in selected]
            views = []
            reused = True
            for qid in selected_ids:
                part = _create_quiz(uid, body.model_copy(update={"question_ids": [qid], "task_id": ""}), save=False)
                views.extend(part["questions"])
                reused = reused and part["reused"]
            return save_group(uid, body, "mixed" if mixed else lecture, views, len(selected_ids), reused)
        return _create_quiz(uid, body)


def _create_quiz(uid, body, save=True):
    lecture = body.lecture_id.strip() or "lec-6"
    original, origin_id, point_id = None, "", ""
    with SessionLocal() as session:
        if body.mode == "review":
            wrong = review_rows(session, uid, manual=bool(body.question_ids))
            allowed = {q.id for _, q in wrong} | {root(q) for _, q in wrong}
            if any(qid not in allowed for qid in body.question_ids):
                raise LookupError()
            selected = [q for _, q in wrong if q.id in body.question_ids or root(q) in body.question_ids]
            if not selected:
                raise PracticeError("这一讲暂时没有可推荐复习的题目")
            # 一次换一道错题；保持一个知识点、只带对应页，避免多讲混杂。
            q = selected[0]
            lecture, point_id, origin_id = q.lecture_id, q.knowledge_point_id, root(q)
            kp = session.scalar(select(KnowledgePoint).where(KnowledgePoint.id == point_id, KnowledgePoint.user_id == uid))
            origin = question(session, uid, origin_id) or q
            original = {"stem": origin.stem, "knowledge_point": kp.name if kp else "原知识点", "page": source(origin).get("page"),
                        "source_quote": source(origin).get("quote", ""), "options": json.loads(origin.options_json),
                        "answer": origin.answer, "analysis": origin.analysis, "question_id": q.id, "previous_stem": q.stem}
        if body.task_id:
            validate_task(session, uid, body.task_id, lecture, body.mode)
    pages = fetch_lecture_pages(uid, lecture)
    # 资料线的占位会对未知讲次退回样例，不能冒充所选讲次的资料。
    if any(p.get("sample") for p in pages) and lecture != "lec-6":
        raise PracticeError("这一讲还没有正文，请先交资料")
    if original:
        pages = [p for p in pages if p["page"] == original["page"]]
    count = 1 if original else body.count
    from app.gateway.llm_gateway import ModelTier, has_llm
    offline = not has_llm(ModelTier.STRONG)
    cache_key = digest([lecture, [{"page": p["page"], "text": p["text"]} for p in pages], count, body.difficulty, origin_id, original, offline,
                        PROMPT_VERSIONS])
    with SessionLocal() as session:
        cached = [q for q in session.scalars(select(Question).where(Question.user_id == uid, Question.lecture_id == lecture)).all()
                  if meta(q).get("cache_key") == cache_key]
        if original:
            attempted = set(session.scalars(select(Attempt.question_id).where(Attempt.user_id == uid)).all())
            cached = [q for q in cached if q.id not in attempted]
    reused = bool(cached)
    if cached:
        views = [public(q) for q in cached]
    else:
        generated, mocked = generate(uid, lecture, pages, count, body.difficulty, original)
        with SessionLocal() as session:
            views = []
            for i, data in enumerate(generated):
                kp_id = point_id or "pk-" + digest([uid, lecture, data.knowledge_point])[:32]
                kp = session.scalar(select(KnowledgePoint).where(KnowledgePoint.id == kp_id, KnowledgePoint.user_id == uid))
                if kp is None:
                    session.add(KnowledgePoint(id=kp_id, user_id=uid, lecture_id=lecture, name=data.knowledge_point,
                                               source_json=dump(data.source.model_dump()), mastery=0, next_review_on=""))
                    session.flush()
                qid = "pq-" + digest([uid, cache_key, data.stem, uuid.uuid4().hex if original else i])[:40]
                src = data.source.model_dump()
                prompt_name = "practice.rephrase" if original else "practice.generate"
                src["practice"] = {"cache_key": cache_key, "mock": mocked, "original_id": origin_id,
                                   "parent_question_id": original.get("question_id", "") if original else "",
                                   "prompt": f"{prompt_name}@{PROMPT_VERSIONS[prompt_name]}"}
                q = Question(id=qid, user_id=uid, lecture_id=lecture, knowledge_point_id=kp_id, kind="single",
                             stem=data.stem, options_json=dump([o.model_dump() for o in data.options]), answer=data.answer,
                             analysis=data.analysis, source_json=dump(src), difficulty=data.difficulty)
                session.add(q)
                views.append(public(q))
            session.commit()
    if not save:
        return {"questions": views, "reused": reused}
    return save_group(uid, body, lecture, views, count, reused)


def save_group(uid, body, lecture, views, count, reused):
    mocked = any(q["mock"] for q in views)
    quiz_id = "quiz-" + uuid.uuid4().hex
    data = {"quiz_id": quiz_id, "lecture_id": lecture, "mode": body.mode, "task_id": body.task_id,
            "question_ids": [q["id"] for q in views], "mock": mocked, "requested_count": count,
            "lecture_ids": sorted({q["lecture_id"] for q in views})}
    with SessionLocal() as session:
        event(session, uid, "practice_quiz_created", data, quiz_id)
        session.commit()
    return {**data, "questions": views, "reused": reused, "label": "模拟" if mocked else "AI 整理，可以改",
            "notice": "部分题目未通过检查，已丢弃。" if len(views) < count else ""}


def mastery_schedule(history: list, previous: dict, correct: bool, now: date, confidence: str = ""):
    """兼容既有调度入口；正确率只看对错，不以把握度加权。"""
    flags = [item[0] if isinstance(item, tuple) else item for item in history]
    mastery = round(100 * sum(bool(x) for x in flags) / len(flags)) if flags else None
    repetitions = int(previous.get("repetitions", 0)) + 1 if correct else 0
    interval = 1 if not correct or repetitions <= 1 else 6 if repetitions == 2 else max(1, int(previous.get("interval", 1)) * 2)
    return {"mastery": mastery, "ease": 2.5, "repetitions": repetitions, "interval": interval,
            "next_review_on": (now + timedelta(days=interval)).isoformat()}


def recompute_learning(session, uid):
    data = learning.snapshot(session, uid)
    points = session.scalars(select(KnowledgePoint).where(KnowledgePoint.user_id == uid)).all()
    for point in points:
        items = [item for item in data["items"] if item["question"].knowledge_point_id == point.id]
        summary = learning.summarize(items)
        point.mastery = round(summary["accuracy"]) if summary["accuracy"] is not None else 0
        dates = [item["next_review_on"] for item in items if item["review_recommended"]]
        point.next_review_on = min(dates, default="")
    return data


def update_mastery(session, uid, q, correct):
    data = recompute_learning(session, uid)
    items = [item for item in data["items"] if item["question"].knowledge_point_id == q.knowledge_point_id]
    summary = learning.summarize(items)
    dates = [item["next_review_on"] for item in items if item["review_recommended"]]
    values = {"mastery": summary["accuracy"], "next_review_on": min(dates, default="")}
    event(session, uid, "practice_review_scheduled", {**values, "knowledge_point_id": q.knowledge_point_id,
                                                     "scope": "latest_attempt_per_original_question"})
    return values


def result(q, a, data=None):
    from app.study.practice.feedback import answer_feedback
    mocked = bool(meta(q).get("mock", True))
    excluded = bool(data and root(q) in data["excluded_roots"])
    state = learning.classification(bool(a.correct), excluded=excluded, practiced=q.id != root(q))
    reports = data["reports"] if data else {}
    report = reports.get(q.id)
    if excluded and not (report and report.get("active")):
        report = next((value for qid, value in reports.items() if value.get("active") and qid in data["questions"]
                       and root(data["questions"][qid]) == root(q)), report)
    return {"attempt_id": a.id, "question_id": q.id, "your_answer": a.answer, "answer": q.answer,
            "correct": bool(a.correct), "score": a.score, "analysis": q.analysis, "source": source(q), "mock": mocked,
            **learning.confidence_info(a.confidence), **state, "report": report,
            "feedback": answer_feedback(bool(a.correct), "", a.id),
            "action_feedback": learning.action_feedback(bool(a.correct), excluded=excluded),
            "label": "模拟" if mocked else "AI 整理，可以改"}


def submit(uid: str, body: AttemptBody):
    ensure_schema()
    try:
        return _submit(uid, body)
    except IntegrityError:
        # 多 worker 同时重传时，由确定的主键保证只保存一次。
        if body.quiz_id:
            stored = get_quiz(uid, body.quiz_id)["results"].get(body.question_id)
            if stored:
                return {**stored, "quiz_completed": get_quiz(uid, body.quiz_id)["completed"]}
        raise


def _submit(uid, body):
    with lock_for(uid), SessionLocal() as session:
        q = question(session, uid, body.question_id)
        if q is None:
            raise LookupError()
        quiz = quiz_record(session, uid, body.quiz_id) if body.quiz_id else None
        if quiz and q.id not in quiz["question_ids"]:
            raise LookupError()
        if body.answer not in [o["id"] for o in json.loads(q.options_json)]:
            raise PracticeError("请选择题目中的一个选项")
        aid = attempt_id(body.quiz_id, q.id) if quiz else uuid.uuid4().hex
        a = session.scalar(select(Attempt).where(Attempt.id == aid, Attempt.user_id == uid))
        if a is None:
            a = Attempt(id=aid, user_id=uid, question_id=q.id, answer=body.answer, correct=int(body.answer == q.answer),
                        score=int(body.answer == q.answer), seconds=body.seconds, confidence="", created_at=_now())
            session.add(a)
            session.flush()
            schedule = update_mastery(session, uid, q, bool(a.correct))
            event(session, uid, "practice_answered", {"attempt_id": a.id, "question_id": q.id,
                                                      "quiz_id": body.quiz_id, "correct": bool(a.correct)})
        else:
            point = session.scalar(select(KnowledgePoint).where(KnowledgePoint.id == q.knowledge_point_id, KnowledgePoint.user_id == uid))
            state = learning.snapshot(session, uid)
            scope = [i for i in state["items"] if i["question"].knowledge_point_id == q.knowledge_point_id]
            schedule = {"mastery": learning.summarize(scope)["accuracy"], "next_review_on": point.next_review_on if point else ""}
        session.flush()
        completed, task_id = False, None
        if quiz:
            ids = [attempt_id(body.quiz_id, qid) for qid in quiz["question_ids"]]
            completed = len(session.scalars(select(Attempt).where(Attempt.user_id == uid, Attempt.id.in_(ids))).all()) == len(ids)
            eid = "done-" + body.quiz_id
            recorded = session.scalar(select(StudyEvent).where(StudyEvent.id == eid, StudyEvent.user_id == uid))
            if completed and recorded is None:
                if quiz["task_id"]:
                    task = validate_task(session, uid, quiz["task_id"], quiz["lecture_id"], quiz["mode"])
                    task.status, task_id = "done", task.id
                # 只标记调用方明确传入的任务，不新增、不撤销任务；同时发布计划线可读的完成事件。
                event(session, uid, "practice_quiz_completed", {"quiz_id": body.quiz_id, "lecture_id": quiz["lecture_id"],
                      "mode": quiz["mode"], "task_id": quiz["task_id"], "count": len(ids)}, eid)
            elif completed:
                task_id = quiz["task_id"] or None
        data = {**result(q, a, learning.snapshot(session, uid)), **schedule, "quiz_completed": completed, "completed_task_id": task_id}
        session.commit()
        return data


def get_quiz(uid: str, quiz_id: str):
    ensure_schema()
    with SessionLocal() as session:
        quiz = quiz_record(session, uid, quiz_id)
        state = learning.snapshot(session, uid)
        questions, results = [], {}
        for qid in quiz["question_ids"]:
            q = question(session, uid, qid)
            if q is None:
                raise LookupError()
            questions.append(public(q))
            a = session.scalar(select(Attempt).where(Attempt.id == attempt_id(quiz_id, qid), Attempt.user_id == uid))
            if a:
                results[qid] = result(q, a, state)
        reports = {qid: value for qid, value in state["reports"].items() if qid in quiz["question_ids"] and value.get("active")}
        summary_items = [{**r, "has_attempt": True} for r in results.values()]
        return {**quiz, "questions": questions, "results": results, "reports": reports,
                "summary": learning.summarize(summary_items), "completed": len(results) == len(questions),
                "label": "模拟" if quiz["mock"] else "AI 整理，可以改"}


def save_progress(uid: str, quiz_id: str, body: ProgressBody):
    ensure_schema()
    with lock_for(uid), SessionLocal() as session:
        quiz = quiz_record(session, uid, quiz_id)
        if body.question_id not in quiz["question_ids"]:
            raise LookupError()
        q = question(session, uid, body.question_id)
        if body.answer and body.answer not in [o["id"] for o in json.loads(q.options_json)]:
            raise PracticeError("请选择题目中的选项")
        row = session.scalar(select(StudyEvent).where(StudyEvent.id == quiz_id, StudyEvent.user_id == uid))
        quiz["progress"] = body.model_dump()
        row.props_json = dump(quiz)
        session.commit()
        return {"progress": body.model_dump(), "message": "进度已保存，随时回来继续。"}


def paused_quizzes(uid: str):
    ensure_schema()
    with SessionLocal() as session:
        rows = session.scalars(select(StudyEvent).where(StudyEvent.user_id == uid,
                               StudyEvent.name == "practice_quiz_created").order_by(StudyEvent.at.desc())).all()
        ids = [row.id for row in rows if json.loads(row.props_json).get("progress", {}).get("paused")]
    items = [get_quiz(uid, quiz_id) for quiz_id in ids]
    return {"items": [q for q in items if not q["completed"]]}


def mistakes(uid: str):
    ensure_schema()
    with SessionLocal() as session:
        items = []
        for a, q in wrong_rows(session, uid):
            p = session.scalar(select(KnowledgePoint).where(KnowledgePoint.id == q.knowledge_point_id, KnowledgePoint.user_id == uid))
            items.append({"attempt_id": a.id, "question_id": q.id, "stem": q.stem, "your_answer": a.answer,
                          "answer": q.answer, "lecture_id": q.lecture_id, "analysis": q.analysis, "source": source(q),
                          "knowledge_point_id": q.knowledge_point_id, "next_review_on": p.next_review_on if p else "",
                          "mock": bool(meta(q).get("mock", True))})
        return {"items": items, "label": "错题记录", "mock": any(x["mock"] for x in items)}


def review_due(uid: str, on: date | None = None):
    ensure_schema()
    day = (on or today()).isoformat()
    with SessionLocal() as session:
        data = learning.snapshot(session, uid)
        items = [item for item in data["items"] if item["review_recommended"] and item["next_review_on"] <= day]
        ids = {item["question"].knowledge_point_id for item in items}
        points = session.scalars(select(KnowledgePoint).where(KnowledgePoint.user_id == uid, KnowledgePoint.id.in_(ids))).all()
        return {"date": day, "knowledge_points": [{"id": p.id, "lecture_id": p.lecture_id, "name": p.name,
                "next_review_on": min(i["next_review_on"] for i in items if i["question"].knowledge_point_id == p.id)} for p in points],
                "mistakes": [{"question_id": item["question"].id, "lecture_id": item["question"].lecture_id,
                              "knowledge_point_id": item["question"].knowledge_point_id} for item in items if not item["attempt"].correct]}


def report(uid, question_id, reason, category=None, quiz_id="", current_attempt_id=""):
    from app.study.practice.reports import save_report
    return save_report(uid, question_id, reason, category, quiz_id, current_attempt_id)


def learning_items(uid, lecture_id=""):
    ensure_schema()
    with SessionLocal() as session:
        data = learning.snapshot(session, uid)
        items = []
        for item in data["items"]:
            q, a = item["question"], item["attempt"]
            if lecture_id and q.lecture_id != lecture_id:
                continue
            entry = {**public(q), "question_id": q.id, "root_id": item["root_id"], "attempt_id": a.id if a else "",
                     "has_attempt": a is not None, "next_review_on": item["next_review_on"],
                     **{key: item[key] for key in ("learning_state", "learning_label", "excluded", "priority", "review_recommended", "review_rank", "review_passed")},
                     "report": item["report"], "history_count": len(item["history"]), "history": []}
            if a:
                entry.update(result(q, a, data))
            for old in item["history"]:
                old_q = data["questions"][old.question_id]
                entry["history"].append({**result(old_q, old, data), "stem": old_q.stem, "created_at": old.created_at})
            items.append(entry)
        items.sort(key=lambda item: (not item["review_recommended"], item["review_rank"] if item["review_rank"] is not None else 99, item["root_id"]))
        return {"items": items, "scope": "同一原题及其复练只取最近一次作答；历史记录完整保留。"}


def stats(uid, lecture_id=""):
    ensure_schema()
    start = datetime.combine(today() - timedelta(days=today().weekday()), datetime.min.time(), ZoneInfo("Asia/Shanghai")).astimezone(ZoneInfo("UTC")).isoformat()
    with SessionLocal() as session:
        data = learning.snapshot(session, uid)
        items = [item for item in data["items"] if not lecture_id or item["question"].lecture_id == lecture_id]
        attempts = [a for a in data["attempts"] if a.created_at >= start and (not lecture_id or data["questions"][a.question_id].lecture_id == lecture_id)]
        lecture_ids = sorted({item["question"].lecture_id for item in items})
        mocked = any(meta(item["question"]).get("mock", True) for item in items)
        summary = learning.summarize(items)
        return {**summary, "mock": mocked, "label": "包含模拟练习记录" if mocked else "练习记录",
                "title": "已练内容掌握情况", "scope": "当前 PDF 下历次练习；同一原题与复练仅取最近一次结果，排除已反馈问题。不代表整个 PDF 的掌握程度。" if lecture_id else "所有 PDF 下历次练习；每条原题链取最近一次结果，排除已反馈问题。",
                "week_attempt_count": len(attempts), "mistakes_pending": summary["wrong_count"],
                "lectures": [{"lecture_id": lid, **learning.summarize([i for i in items if i["question"].lecture_id == lid])} for lid in lecture_ids]}
