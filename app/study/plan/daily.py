"""今天这一天里的几样东西：收工卡、引导下一件、调强度的建议卡、快捷回复。

这里只做计算和文案，不读写数据库；``service.py`` 负责取数据和存卡。
文案是占位，最终以 A 给的为准；不追责、不连续打卡。
"""

from __future__ import annotations

from typing import Any, Optional

from app.study.plan import parse

BADGE = "模拟"
INTENSITY_LABEL = {"light": "轻松", "normal": "正常", "sprint": "冲刺"}
INTENSITY_MINUTES = {"light": 15, "normal": 30, "sprint": 50}
KIND_ADJUST = "adjust_intensity"

_LESS = ("少一点", "累", "没时间", "时间不多", "忙", "轻松点", "轻一点", "简单点")
_MORE = ("多学", "多做", "再来点", "多一点", "加点量", "冲一冲")


# ---------- 收工卡 ----------


def done_card(today_tasks: list[dict[str, Any]], tomorrow_tasks: list[dict[str, Any]], *, milestone: Optional[str]) -> dict[str, Any]:
    lines = [f"今天的 {len(today_tasks)} 件都做完了，辛苦啦"]
    if milestone:
        lines.append(milestone)
    if tomorrow_tasks:
        lines.append("明天的三件：" + "；".join(f"{t['kind_label']}·{t['title']}" for t in tomorrow_tasks))
    else:
        lines.append("明天先不排任务，想学的时候随时回来")
    return {
        "kind": "done",
        "type": "done",
        "title": "今天收工啦",
        "lines": lines,
        "badge": BADGE,
        "collapsed_text": "今天收工了",
        "options": [{"id": "dashboard", "label": "看看板"}],
        "tomorrow": tomorrow_tasks,
        "mood": "celebrate",
    }


def milestone_text(done_learn_refs: list[dict[str, Any]], *, learned_up_to: int, lecture_count: int) -> Optional[str]:
    if lecture_count and learned_up_to >= lecture_count and done_learn_refs:
        return f"全部 {lecture_count} 讲都过了一遍，接下来以刷题为主"
    if not done_learn_refs:
        return None
    ref = done_learn_refs[-1]
    nos = ref.get("lecture_nos") or [ref.get("lecture_no")]
    label = "、".join(str(n) for n in nos if n)
    if ref.get("source") == "upload":
        return f"第 {label} 讲的课件交上了"
    return f"第 {label} 讲学完了"


# ---------- 引导下一件 ----------


def next_prompt(task: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if task is None:
        return None
    return {
        "task_id": task["id"],
        "text": f"下一件：{task['kind_label']}·{task['title']}",
        "options": [{"id": "start", "label": "开始"}, {"id": "later", "label": "晚点再做"}],
    }


# ---------- “今天只有 15 分钟”：调强度 ----------


def wanted_intensity(text: str) -> Optional[str]:
    """从一句话里看用户想换哪一档；看不出来返回 None。"""
    raw = (text or "").replace(" ", "")
    level = parse.parse_intensity(raw)
    if level:
        return level
    minutes = parse.parse_minutes(raw) if any(w in raw for w in ("分钟", "小时", "钟头")) else None
    if minutes is not None:
        if minutes <= 20:
            return "light"
        if minutes <= 40:
            return "normal"
        return "sprint"
    if any(word in raw for word in _LESS):
        return "light"
    if any(word in raw for word in _MORE):
        return "sprint"
    return None


def adjust_card(target: str) -> dict[str, Any]:
    minutes = INTENSITY_MINUTES[target]
    body = {
        "light": f"还是三件，每件少一点，大约 {minutes} 分钟",
        "normal": f"还是三件，回到正常的分量，大约 {minutes} 分钟",
        "sprint": f"还是三件，每件多一点，大约 {minutes} 分钟",
    }[target]
    return {
        "kind": KIND_ADJUST,
        "type": "suggestion",
        "title": f"今天换成{INTENSITY_LABEL[target]}",
        "lines": [body, "点了才生效，也可以撤销"],
        "badge": BADGE,
        "collapsed_text": f"今天按{INTENSITY_LABEL[target]}来",
        "decline_label": "先不用",
        "options": [{"id": "apply", "label": "就这样", "effect": {"intensity": target}}],
    }


def same_level_reply(level: str) -> str:
    return f"今天已经是{INTENSITY_LABEL[level]}了，还是三件，大约 {INTENSITY_MINUTES[level]} 分钟"


NOT_UNDERSTOOD = "可以说“今天只有 15 分钟”或“今天想多学点”，我来出个建议"


# ---------- 快捷回复：只给当下说得通的 ----------


def quick_replies(*, needs_setup: bool, has_card: bool, intensity: str, first_task: Optional[dict[str, Any]], all_done: bool, has_tasks: bool) -> list[dict[str, Any]]:
    if has_card:
        return []  # 一次只让用户做一个决定：先处理卡片
    if needs_setup:
        return [{"text": "定个学习目标", "action": "goal_setup"}]
    replies: list[dict[str, Any]] = []
    if all_done:
        replies.append({"text": "看看明天的三件", "action": "tomorrow"})
        replies.append({"text": "这周学得怎么样", "action": "dashboard"})
        return replies
    if first_task:
        replies.append({"text": f"开始：{first_task['title']}", "action": "start_task", "task_id": first_task["id"]})
    if has_tasks and intensity != "light":
        replies.append({"text": "今天只有 15 分钟", "action": "adjust"})
    if has_tasks and intensity != "sprint":
        replies.append({"text": "今天想多学点", "action": "adjust"})
    return replies
