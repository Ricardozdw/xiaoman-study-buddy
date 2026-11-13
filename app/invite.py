"""邀请码登录：配置了 INVITE_CODES 时，必须用邀请码才能进入。

- INVITE_CODES：逗号分隔的 ``码:标签``（如 ``XM-ABCD-EFGH:试用1,XM-...:试用2``），只放在线上环境变量里，不进仓库。
- 一个码就是一个账号：同一个码在手机、电脑上登录看到的是同一份学习数据；码可重复使用、不过期。
- 账号 id 由码推导（``u_inv_`` + 哈希），不存表；码本身不进日志、不进数据库。
- 开启后，以前的匿名会话一律失效（只认邀请码账号）。
- 没配置 INVITE_CODES（本地开发、验收环境）时行为不变：自动建匿名用户。
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import threading
import time
from collections import deque
from typing import Optional

INVITE_PREFIX = "u_inv_"
_FAILS_PER_WINDOW, _WINDOW_SECONDS = 10, 600
_fails: dict[str, deque] = {}
_lock = threading.Lock()


def _norm(code: str) -> str:
    """大小写、空格、横线都不敏感：xm-abcd efgh 和 XM-ABCD-EFGH 是同一个码。"""
    return re.sub(r"[\s\-_]", "", (code or "").upper())


def codes() -> dict[str, str]:
    """{规范化后的码: 标签}；每次读环境变量，改了不用重启进程里的缓存。"""
    out: dict[str, str] = {}
    for item in (os.getenv("INVITE_CODES") or "").split(","):
        code, _, label = item.strip().partition(":")
        if _norm(code):
            out[_norm(code)] = label.strip() or "未标注"
    return out


def invite_required() -> bool:
    return bool(codes())


def user_for_code(code: str) -> str:
    return INVITE_PREFIX + hashlib.sha256(("xiaoman-invite:" + _norm(code)).encode("utf-8")).hexdigest()[:24]


def is_invite_user(user_id: Optional[str]) -> bool:
    return bool(user_id) and str(user_id).startswith(INVITE_PREFIX)


def check(code: str) -> Optional[str]:
    """码有效返回标签，否则 None。逐个常量时间比较，不因长度/前缀泄露信息。"""
    given = _norm(code)
    found = None
    for known, label in codes().items():
        if hmac.compare_digest(given.encode(), known.encode()):
            found = label
    return found


def too_many_failures(client: str) -> bool:
    now = time.monotonic()
    with _lock:
        q = _fails.setdefault(client, deque())
        while q and now - q[0] > _WINDOW_SECONDS:
            q.popleft()
        return len(q) >= _FAILS_PER_WINDOW


def record_failure(client: str) -> None:
    with _lock:
        _fails.setdefault(client, deque()).append(time.monotonic())


def client_key(headers: dict[str, str], fallback: str = "") -> str:
    """云托管把真实来源地址放在 x-envoy-external-address；本地直连用对端地址。"""
    return (headers.get("x-envoy-external-address") or headers.get("x-forwarded-for", "").split(",")[0]
            or fallback or "unknown").strip()
