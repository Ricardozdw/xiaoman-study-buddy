"""计划线排程规则：从三处来源算出今天最多三件。

这里只做计算，不读写数据库，方便单测。读数据、存计划在 ``service.py``。

规则（PRD F5 / 产品规则 1、4、5）：
- 每天最多三件，各从一处来：学新的 / 练一练 / 补一补。
- 某处没东西，由另外两处多出一件顶上；永远不超过三件。
- 有之前做错的题时，补一补排第一，标“先做这件”。
- 目标暂停（先休息一阵）或没有目标时，不排任务。
- 强度只改每件的分量，件数不变。
- 文案不提断了几天，不责备。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

MAX_TASKS = 3
KINDS = ("learn", "practice", "repair")
KIND_LABEL = {"learn": "学新的", "practice": "练一练", "repair": "补一补"}

# 每档强度下各类任务的分量。件数不变，变的是这里。
PRACTICE_COUNT = {"light": 3, "normal": 5, "sprint": 8}
REDO_CAP = {"light": 2, "normal": 3, "sprint": 5}
REVIEW_AMOUNT = {"light": "看一眼要点", "normal": "看要点，再做 2 道题", "sprint": "看要点，再做 3 道题"}
LEARN_AMOUNT = {"light": "看要点", "normal": "看要点和知识点", "sprint": "看完整学习文档"}

# 掌握度到这个数以上的知识点，不再排进“补一补”的复习。
REVIEW_MASTERY_LINE = 80


@dataclass(frozen=True)
class LectureState:
    number: int
    lecture_id: str
    title: str
    has_material: bool = False
    mastery: Optional[int] = None  # 这一讲知识点的平均掌握度，没有知识点时为 None
    last_practiced: Optional[date] = None


@dataclass(frozen=True)
class MistakeItem:
    question_id: str
    lecture_id: str
    wrong_on: date


@dataclass(frozen=True)
class ReviewItem:
    point_id: str
    name: str
    lecture_id: str
    mastery: int
    due_on: date


@dataclass(frozen=True)
class PlanInputs:
    today: date
    goal_active: bool
    lecture_count: int
    learned_up_to: int
    lectures: tuple[LectureState, ...] = ()
    mistakes: tuple[MistakeItem, ...] = ()
    reviews: tuple[ReviewItem, ...] = ()
    # 中断后回来选了补法时：一次学两讲。mode 是 sprint（冲刺补课）或 skim（只看要点）。
    learn_per_task: int = 1
    learn_mode: str = ""


@dataclass
class TaskDraft:
    kind: str
    ref: dict[str, Any] = field(default_factory=dict)


# ---------- 各来源的候选 ----------


def _lecture_map(inputs: PlanInputs) -> dict[int, LectureState]:
    return {item.number: item for item in inputs.lectures}


def _learn_candidates(inputs: PlanInputs) -> list[TaskDraft]:
    lectures = _lecture_map(inputs)
    per_task = 2 if inputs.learn_per_task >= 2 else 1
    numbers = list(range(inputs.learned_up_to + 1, inputs.lecture_count + 1))
    out: list[TaskDraft] = []
    for start in range(0, len(numbers), per_task):
        group = numbers[start : start + per_task]
        states = [lectures.get(n) for n in group]
        ready = all(state is not None and state.has_material for state in states)
        ref: dict[str, Any] = {
            "source": "lecture" if ready else "upload",
            "lecture_no": group[0],
            "lecture_id": states[0].lecture_id if states[0] else lecture_id_for(group[0]),
        }
        if per_task == 2:
            ref["lecture_nos"] = group
            ref["mode"] = inputs.learn_mode or "sprint"
        out.append(TaskDraft("learn", ref))
        if len(out) >= 2:  # 一天最多两件学新的，再多就不合理了
            break
    return out


def _practice_candidates(inputs: PlanInputs) -> list[TaskDraft]:
    learned = [
        item
        for item in inputs.lectures
        if item.number <= inputs.learned_up_to and item.has_material
    ]
    # 掌握度低的先练；同样低的，隔得久（或从没练过）的先练。
    learned.sort(
        key=lambda item: (
            item.mastery if item.mastery is not None else 0,
            item.last_practiced or date.min,
            item.number,
        )
    )
    return [
        TaskDraft("practice", {"source": "quiz", "lecture_no": item.number, "lecture_id": item.lecture_id})
        for item in learned
    ]


def _repair_candidates(inputs: PlanInputs) -> list[TaskDraft]:
    numbers = {item.lecture_id: item.number for item in inputs.lectures}
    out: list[TaskDraft] = []
    # 之前做错的题，按讲合成一件，最早错的那一讲排前面。今天刚错的不算。
    groups: dict[str, list[MistakeItem]] = {}
    for item in inputs.mistakes:
        if item.wrong_on < inputs.today:
            groups.setdefault(item.lecture_id, []).append(item)
    for lecture_id, items in sorted(groups.items(), key=lambda kv: (min(i.wrong_on for i in kv[1]), kv[0])):
        items.sort(key=lambda i: (i.wrong_on, i.question_id))
        out.append(
            TaskDraft(
                "repair",
                {
                    "source": "mistakes",
                    "lecture_id": lecture_id,
                    "lecture_no": numbers.get(lecture_id) or lecture_no_for(lecture_id),
                    "question_ids": [i.question_id for i in items],
                },
            )
        )
    # 再是到期、还没掌握的知识点。
    due = [
        item
        for item in inputs.reviews
        if item.due_on <= inputs.today and item.mastery < REVIEW_MASTERY_LINE
    ]
    due.sort(key=lambda i: (i.mastery, i.due_on, i.point_id))
    for item in due:
        out.append(
            TaskDraft(
                "repair",
                {
                    "source": "review",
                    "lecture_id": item.lecture_id,
                    "lecture_no": numbers.get(item.lecture_id) or lecture_no_for(item.lecture_id),
                    "point_id": item.point_id,
                    "point_name": item.name,
                    "mastery": item.mastery,
                },
            )
        )
    return out


# ---------- 排程 ----------


def _same(a: TaskDraft, b: TaskDraft) -> bool:
    return a.kind == b.kind and a.ref == b.ref


def schedule(inputs: PlanInputs) -> list[TaskDraft]:
    """算出今天最多三件，已排好顺序，第一件就是“先做这件”。"""
    if not inputs.goal_active:
        return []
    pools = {
        "learn": _learn_candidates(inputs),
        "practice": _practice_candidates(inputs),
        "repair": _repair_candidates(inputs),
    }
    picked: list[TaskDraft] = []
    # 第一轮：每处各取一件。
    for kind in KINDS:
        if pools[kind]:
            picked.append(pools[kind].pop(0))
    # 顶上：某处没东西时，按 补一补 → 练一练 → 学新的 轮流补，直到三件或都空。
    while len(picked) < MAX_TASKS and any(pools.values()):
        for kind in ("repair", "practice", "learn"):
            if len(picked) >= MAX_TASKS:
                break
            while pools[kind]:
                candidate = pools[kind].pop(0)
                if not any(_same(candidate, item) for item in picked):
                    picked.append(candidate)
                    break
    picked = picked[:MAX_TASKS]

    # 顺序：有错题要重做时补一补先做；否则按 学新的 → 练一练 → 补一补。
    has_redo = any(t.kind == "repair" and t.ref.get("source") == "mistakes" for t in picked)
    if has_redo:
        order = {"repair": 0, "learn": 1, "practice": 2}
    else:
        order = {"learn": 0, "practice": 1, "repair": 2}
    picked.sort(key=lambda t: (order[t.kind], 0 if t.ref.get("source") == "mistakes" else 1))
    return picked


# ---------- 文案：按当前强度把一件任务说清楚 ----------


def describe(kind: str, ref: dict[str, Any], intensity: str) -> dict[str, str]:
    """返回 title / amount / reason / done_when。强度变了重新算，不改件数。"""
    level = intensity if intensity in PRACTICE_COUNT else "normal"
    no = ref.get("lecture_no")
    nos = ref.get("lecture_nos") or []
    if len(nos) >= 2:
        lecture = f"第 {nos[0]}、{nos[-1]} 讲"
    else:
        lecture = f"第 {no} 讲" if no else "这一讲"
    source = ref.get("source")
    if kind == "learn" and source == "upload":
        return {
            "title": f"交{lecture}课件",
            "amount": "交上来就算完成，小满会整理成学习文档",
            "reason": f"按进度该学{lecture}了，先把课件交上来",
            "done_when": "课件交上来",
        }
    if kind == "learn" and ref.get("mode") == "skim":
        return {
            "title": f"学{lecture}",
            "amount": "只看要点",
            "reason": "按选好的补法，这几讲先看要点",
            "done_when": "看完就算完成",
        }
    if kind == "learn" and len(nos) >= 2:
        return {
            "title": f"学{lecture}",
            "amount": LEARN_AMOUNT[level],
            "reason": "按选好的补法，这几天一次学两讲",
            "done_when": "看完就算完成",
        }
    if kind == "learn":
        return {
            "title": f"学{lecture}",
            "amount": LEARN_AMOUNT[level],
            "reason": f"按进度该学{lecture}了",
            "done_when": "看完就算完成",
        }
    if kind == "practice":
        count = PRACTICE_COUNT[level]
        extra = "，含难题" if level == "sprint" else ""
        return {
            "title": f"{lecture}做 {count} 道题",
            "amount": f"{count} 道单选题{extra}",
            "reason": f"{lecture}学过了，练一练记得更牢",
            "done_when": "做完一组题",
        }
    if kind == "repair" and source == "mistakes":
        total = len(ref.get("question_ids") or [])
        count = max(1, min(total, REDO_CAP[level]))
        return {
            "title": f"重做{lecture}的 {count} 道错题",
            "amount": f"{count} 道，换个问法再做一次",
            "reason": "上次做错的题，换个问法再试试，常错没关系",
            "done_when": "做完这几道",
        }
    if kind == "repair":
        name = ref.get("point_name") or "还没掌握的那一点"
        return {
            "title": f"复习「{name}」",
            "amount": REVIEW_AMOUNT[level],
            "reason": f"{lecture}的这一点还没完全掌握，到了该复习的时候",
            "done_when": "看完要点",
        }
    return {"title": "今天的一件事", "amount": "", "reason": "", "done_when": "做完就算"}


# ---------- 讲次编号约定（待和资料线确认）----------


def lecture_id_for(number: int) -> str:
    return f"lec-{number}"


def last_lecture_no(ref: dict[str, Any]) -> Optional[int]:
    """一件学新的覆盖到第几讲（一次两讲时取后一讲）。"""
    nos = [n for n in (ref.get("lecture_nos") or []) if isinstance(n, int)]
    if nos:
        return max(nos)
    no = ref.get("lecture_no")
    return no if isinstance(no, int) else None


def first_lecture_no(ref: dict[str, Any]) -> Optional[int]:
    nos = [n for n in (ref.get("lecture_nos") or []) if isinstance(n, int)]
    if nos:
        return min(nos)
    no = ref.get("lecture_no")
    return no if isinstance(no, int) else None


def lecture_no_for(lecture_id: str) -> Optional[int]:
    raw = (lecture_id or "").strip()
    if raw.startswith("lec-") and raw[4:].isdigit():
        return int(raw[4:])
    return None
