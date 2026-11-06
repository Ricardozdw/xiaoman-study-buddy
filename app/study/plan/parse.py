"""把用户的一句话解析成计划参数：日期、讲数、学到第几讲、每天时间、强度。

只用规则，不用 AI（PRD：目标拆解用后端规则算）。解析不出来就返回 None，
调用方按“先按……安排”处理，不把默认值当成用户的选择。
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Optional

NO_DATE = "none"  # 用户明确说“还没定”

_CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_NUM = "零〇一二两三四五六七八九十百"


def cn_to_int(text: str) -> Optional[int]:
    """一、十二、二十、二十五、一百 这类中文数字。"""
    raw = (text or "").strip()
    if not raw or any(ch not in _CN_NUM for ch in raw):
        return None
    if "百" in raw:
        head, _, tail = raw.partition("百")
        hundreds = _CN_DIGIT.get(head, 1) if head else 1
        rest = cn_to_int(tail.lstrip("零〇")) if tail else 0
        return hundreds * 100 + (rest or 0)
    if "十" in raw:
        head, _, tail = raw.partition("十")
        tens = _CN_DIGIT.get(head, 1) if head else 1
        ones = _CN_DIGIT.get(tail, 0) if tail else 0
        return tens * 10 + ones
    if len(raw) == 1:
        return _CN_DIGIT.get(raw)
    return None


_NUM = rf"(\d+|[{_CN_NUM}]+)"


def _to_int(token: str) -> Optional[int]:
    if token.isdigit():
        return int(token)
    return cn_to_int(token)


def parse_int(text: str) -> Optional[int]:
    match = re.search(_NUM, text or "")
    return _to_int(match.group(1)) if match else None


def parse_minutes(text: str) -> Optional[int]:
    raw = (text or "").replace(" ", "")
    if not raw:
        return None
    if "一个半小时" in raw or "个半小时" in raw:
        hours = parse_int(raw.split("个半小时")[0]) or 1
        return hours * 60 + 30
    if "半小时" in raw or "半个小时" in raw:
        return 30
    match = re.search(_NUM + r"个?(?:小时|钟头|h)", raw)
    if match:
        value = _to_int(match.group(1))
        return value * 60 if value else None
    match = re.search(_NUM + r"(?:分钟|分|min)", raw)
    if match:
        return _to_int(match.group(1))
    value = parse_int(raw)
    if value is not None and 5 <= value <= 300:
        return value
    return None


def parse_date(text: str, today: date) -> Optional[str]:
    """返回 YYYY-MM-DD；用户说“还没定”返回 NO_DATE；解析不出返回 None。"""
    raw = (text or "").replace(" ", "")
    if not raw:
        return None
    if any(word in raw for word in ("没定", "未定", "不确定", "不知道", "还没想好", "不考")):
        return NO_DATE
    match = re.search(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", raw)
    if match:
        try:
            return date(int(match[1]), int(match[2]), int(match[3])).isoformat()
        except ValueError:
            return None
    match = re.search(_NUM + r"月" + _NUM + r"[日号]?", raw)
    if match:
        month, day = _to_int(match.group(1)), _to_int(match.group(2))
        if month and day:
            try:
                value = date(today.year, month, day)
            except ValueError:
                return None
            if value <= today:
                try:
                    value = date(today.year + 1, month, day)
                except ValueError:
                    return None
            return value.isoformat()
    if "下个月" in raw or "下月" in raw:
        return (today + timedelta(days=30)).isoformat()
    match = re.search(_NUM + r"个?(月|周|星期|礼拜|天)(?:后|以后|之后)?", raw)
    if match:
        count = _to_int(match.group(1)) or 0
        unit = {"月": 30, "周": 7, "星期": 7, "礼拜": 7, "天": 1}[match.group(2)]
        if count > 0:
            return (today + timedelta(days=count * unit)).isoformat()
    return None


def parse_lecture_count(text: str) -> Optional[int]:
    raw = (text or "").replace(" ", "")
    if any(word in raw for word in ("不清楚", "不知道", "不确定")):
        return None
    match = re.search(_NUM + r"[讲节章课]", raw)
    value = _to_int(match.group(1)) if match else parse_int(raw)
    return value if value and 1 <= value <= 200 else None


def parse_learned(text: str) -> Optional[int]:
    raw = (text or "").replace(" ", "")
    if not raw:
        return None
    if any(word in raw for word in ("还没开始", "没开始", "刚开始", "从头", "从第一讲", "从第1讲", "零")):
        return 0
    match = re.search(r"第?" + _NUM + r"[讲节章课]", raw)
    if match:
        return _to_int(match.group(1))
    value = parse_int(raw)
    return value if value is not None and 0 <= value <= 200 else None


def parse_intensity(text: str) -> Optional[str]:
    raw = text or ""
    for word, level in (("轻松", "light"), ("冲刺", "sprint"), ("正常", "normal")):
        if word in raw:
            return level
    return None


def revise(text: str, today: date) -> dict[str, Any]:
    """“说说怎么改”：一句话改一项或几项。返回要改的字段；听不懂返回空。"""
    raw = (text or "").replace(" ", "")
    changes: dict[str, Any] = {}
    if any(word in raw for word in ("考试", "日期", "月", "号", "延后", "提前", "没定")):
        value = parse_date(raw, today)
        if value is not None:
            changes["exam_date"] = value
    if any(word in raw for word in ("一共", "总共", "共有", "总")) and re.search(r"[讲节章课]", raw):
        value = parse_lecture_count(raw)
        if value is not None:
            changes["lecture_count"] = value
    if any(word in raw for word in ("学到", "学了", "学完", "开始", "看到")):
        value = parse_learned(raw)
        if value is not None:
            changes["learned_up_to"] = value
    if re.search(r"分钟|小时|钟头", raw):
        value = parse_minutes(raw)
        if value is not None:
            changes["daily_minutes"] = value
    level = parse_intensity(raw)
    if level is not None:
        changes["intensity"] = level
    return changes
