"""V2 最小版的显式开关；不缓存环境变量。"""
import os


def enabled() -> bool:
    return (os.getenv("XIAOMAN_V2") or "").strip().lower() in {"1", "true"}
