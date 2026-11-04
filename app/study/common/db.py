"""学习表的建表入口。本地默认 SQLite；Postgres 不在应用启动时改表。"""

from __future__ import annotations

from app import db


def ensure_schema() -> None:
    """登记学习表并在 SQLite 上创建。Postgres 只建表不在这里做（见 schema.sql）。"""
    import app.study.common.models  # noqa: F401  注册到 Base.metadata

    db.init_db()
    if db.ENGINE.dialect.name == "sqlite":
        db.Base.metadata.create_all(db.ENGINE)
