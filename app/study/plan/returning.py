"""中断后回来（PRD F6）：判断是哪种情况、算落后多少、生成卡片内容。

这里只做计算，不读写数据库。触发、接受、撤销在 ``service.py``。

- 隔 1 天：正常的第二天，不出卡。
- 隔 2–7 天：看“空余天”（离考试还有几天 − 还没学的讲数，按一天一讲算）。
  空余天 ≥ 复习底线，或没填考试日期 → 建议卡：今天轻松一点，前面的讲从复习时间里补上。
  空余天 < 复习底线 → 重排卡：给 2–3 种行得通的补法选一种。
- 隔 8 天及以上，或考试日期已经过了 → 目标卡：照旧 / 考试日期变了 / 先休息一阵。

文案是占位，最终以 A 给的为准；不提断了几天，不责备（测试会扫禁用词）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional

REVIEW_FLOOR_DAYS = 7  # 复习底线：默认留一个刷题周。F1 做完后可按目标存进 goal。
GOAL_CHECK_AWAY_DAYS = 8
RETURN_AWAY_DAYS = 2
BADGE = "模拟"

# 卡片文案里不能出现的说法（产品规则 4）。
BANNED_WORDS = ("断了", "没来", "落下", "落后", "连续", "打卡", "欠", "拖", "又错", "怎么才")

KIND_LIGHT = "return_light"
KIND_RESCHEDULE = "return_reschedule"
KIND_GOAL = "return_goal"


@dataclass(frozen=True)
class ReturnContext:
    today: date
    last_open: Optional[date]
    goal_active: bool
    exam_date: Optional[date]
    lecture_count: int
    learned_up_to: int
    review_floor: int = REVIEW_FLOOR_DAYS


def away_days(ctx: ReturnContext) -> Optional[int]:
    if ctx.last_open is None:
        return None
    return (ctx.today - ctx.last_open).days


def remaining_lectures(ctx: ReturnContext) -> int:
    return max(ctx.lecture_count - ctx.learned_up_to, 0)


def days_left(ctx: ReturnContext) -> Optional[int]:
    if ctx.exam_date is None:
        return None
    return (ctx.exam_date - ctx.today).days


def spare_days(ctx: ReturnContext) -> Optional[int]:
    left = days_left(ctx)
    if left is None:
        return None
    return left - remaining_lectures(ctx)


def classify(ctx: ReturnContext) -> Optional[str]:
    """回来时该出哪种卡；不用出卡返回 None。"""
    away = away_days(ctx)
    if not ctx.goal_active or away is None or away < RETURN_AWAY_DAYS:
        return None
    if away >= GOAL_CHECK_AWAY_DAYS:
        return KIND_GOAL
    return behind_kind(ctx)


def behind_kind(ctx: ReturnContext) -> str:
    """只看落后多少（目标卡选了“照旧”之后也用它决定下一张）。"""
    left = days_left(ctx)
    if left is not None and left <= 0:
        return KIND_GOAL  # 考试日期已经过了，先问目标
    spare = spare_days(ctx)
    if spare is None or spare >= ctx.review_floor:
        return KIND_LIGHT
    if not reschedule_options(ctx):
        return KIND_LIGHT
    return KIND_RESCHEDULE


def catch_up_days(ctx: ReturnContext) -> int:
    """一次学两讲要几天，才能把复习时间补回底线。每这样一天多出一天空余。"""
    spare = spare_days(ctx) or 0
    shortfall = max(ctx.review_floor - spare, 0)
    return min(shortfall, math.ceil(remaining_lectures(ctx) / 2))


def reschedule_options(ctx: ReturnContext) -> list[dict[str, Any]]:
    """只给行得通的补法。每个选项带上生效后要改什么（effect）。"""
    spare = spare_days(ctx)
    remaining = remaining_lectures(ctx)
    options: list[dict[str, Any]] = []
    days = catch_up_days(ctx)
    if remaining >= 2 and days > 0:
        until = (ctx.today + timedelta(days=days - 1)).isoformat()
        options.append(
            {
                "id": "catch_up_sprint",
                "label": f"接下来 {days} 天用冲刺，一次学两讲",
                "effect": {"pace": {"mode": "sprint", "per_task": 2, "until": until}, "intensity": "sprint"},
            }
        )
    if spare is not None and spare >= 1:
        options.append(
            {
                "id": "compress_review",
                "label": f"刷题周缩短到 {spare} 天，每天还是正常强度",
                "effect": {"review_floor": spare},
            }
        )
    if remaining >= 2 and days > 0:
        until = (ctx.today + timedelta(days=days - 1)).isoformat()
        options.append(
            {
                "id": "skim_some",
                "label": f"接下来 {min(days * 2, remaining)} 讲先只看要点，一次两讲",
                "effect": {"pace": {"mode": "skim", "per_task": 2, "until": until}},
            }
        )
    return options


def build_card(kind: str, ctx: ReturnContext) -> dict[str, Any]:
    """卡片内容：按现有卡片组件的字段，再加一组选项。"""
    if kind == KIND_GOAL:
        exam = f"考试日期：{ctx.exam_date.isoformat()}" if ctx.exam_date else "还没定考试日期"
        return {
            "kind": KIND_GOAL,
            "type": "suggestion",
            "title": "目标还算数吗？",
            "lines": [exam, "选一个就好，点了才生效，也可以撤销"],
            "badge": BADGE,
            "collapsed_text": "目标已确认",
            "decline_label": "先不用",
            "options": [
                {"id": "keep", "label": "照旧", "effect": {}},
                {"id": "exam_date", "label": "考试日期变了", "needs": "exam_date", "effect": {}},
                {"id": "rest", "label": "先休息一阵", "effect": {"goal_status": "paused"}},
            ],
        }
    if kind == KIND_RESCHEDULE:
        left = days_left(ctx)
        return {
            "kind": KIND_RESCHEDULE,
            "type": "reschedule",
            "title": "接下来怎么安排",
            "lines": [
                f"离考试还有 {left} 天，还有 {remaining_lectures(ctx)} 讲没学",
                "选一种你觉得舒服的补法，考试日期不变",
                "点了才生效，也可以撤销",
            ],
            "badge": BADGE,
            "collapsed_text": "已选好一种安排",
            "decline_label": "先不用",
            "options": reschedule_options(ctx),
        }
    return {
        "kind": KIND_LIGHT,
        "type": "suggestion",
        "title": "今天先轻松一点",
        "lines": [
            "还是三件，每件少一点，大约 15 分钟",
            "前面的讲从复习时间里补上，考试安排不变",
            "点了才生效，也可以撤销",
        ],
        "badge": BADGE,
        "collapsed_text": "今天按轻松来",
        "decline_label": "先不用",
        "options": [{"id": "light_today", "label": "就这样", "effect": {"intensity": "light"}}],
    }


def card_text(card: dict[str, Any]) -> str:
    """卡片上用户能看到的所有字，给禁用词检查用。"""
    parts = [card.get("title", ""), card.get("collapsed_text", ""), card.get("decline_label", "")]
    parts += list(card.get("lines") or [])
    parts += [option.get("label", "") for option in card.get("options") or []]
    return " ".join(parts)
