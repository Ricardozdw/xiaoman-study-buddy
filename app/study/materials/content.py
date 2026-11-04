"""取资料内容的替换口。问答、练习只调用这里。

现在：返回某一讲的全文，按页，带页码。
以后换知识库：只改这个函数，改成返回检索到的片段，别的线不用动。
"""

from __future__ import annotations

from sqlalchemy import select

from app.data_access.session import SessionLocal
from app.study.common.db import ensure_schema
from app.study.common.models import MaterialPage

# 自写的公开样例，不是某门课的课件。
SAMPLE_LECTURE_ID = "lec-6"
SAMPLE_PAGES: tuple[dict, ...] = (
    {
        "page": 1,
        "text": "每天最多三件事，分别来自学新的、练一练、补一补。想多学，就把每件做深一点，不增加件数。",
    },
    {
        "page": 2,
        "text": "做了就算完成。对错只影响掌握度。没做的不堆到今天。",
    },
)


def fetch_lecture_pages(user_id: str, lecture_id: str) -> list[dict]:
    """按讲返回带页码的正文。没有存档时退回内置样例，并标明 mock。"""
    ensure_schema()
    lecture = (lecture_id or SAMPLE_LECTURE_ID).strip() or SAMPLE_LECTURE_ID
    with SessionLocal() as session:
        rows = session.scalars(
            select(MaterialPage)
            .where(MaterialPage.user_id == user_id, MaterialPage.lecture_id == lecture)
            .order_by(MaterialPage.page_no)
        ).all()
        if rows:
            return [
                {
                    "lecture_id": lecture,
                    "page": row.page_no,
                    "text": row.text,
                    "mock": False,
                }
                for row in rows
            ]
    return [
        {
            "lecture_id": lecture,
            "page": item["page"],
            "text": item["text"],
            "mock": True,
            "sample": True,
        }
        for item in SAMPLE_PAGES
    ]
