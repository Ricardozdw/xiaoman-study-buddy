"""没交资料时，讲解生成后要把讲解正文写进这一讲的“通用知识资料”，出题和问答才有内容可依。"""
import uuid

from app.data_access.session import SessionLocal
from app.study.common.db import ensure_schema
from app.study.common.models import MaterialPage
from app.study.v2 import lecture

SECTIONS = [
    {"heading": "关键路径是什么", "content": "关键路径是网络图中耗时最长的路径。", "example": "装修时水电没完工就不能贴砖。"},
    {"heading": "怎么找", "content": "先顺推最早时间，再逆推最晚时间。", "example": ""},
]


def test_material_text_has_every_section_and_skips_empty_example():
    text = lecture.material_text("关键路径法", SECTIONS)
    assert text.splitlines()[0] == "关键路径法"
    assert "关键路径是网络图中耗时最长的路径。" in text
    assert "例：装修时水电没完工就不能贴砖。" in text
    assert text.count("例：") == 1


def _page(user, outline, no, page_id=None):
    ensure_schema()
    with SessionLocal() as session:
        session.add(MaterialPage(id=page_id or f"v2-outline-{outline}-page-{no}", user_id=user, lecture_id=f"lec-{no}",
                                 file_id=f"v2-outline-{outline}-{no}", page_no=1, text="关键路径法\n要点一\n要点二"))
        session.commit()


def _text(page_id):
    with SessionLocal() as session:
        return session.get(MaterialPage, page_id).text


def test_sync_replaces_outline_page_with_lecture_text():
    user, outline = "u-" + uuid.uuid4().hex, uuid.uuid4().hex
    _page(user, outline, 2)
    lecture._sync_material(user, outline, 2, "关键路径法", SECTIONS)
    assert _text(f"v2-outline-{outline}-page-2") == lecture.material_text("关键路径法", SECTIONS)


def test_sync_never_touches_other_users_or_missing_pages():
    owner, outline = "u-" + uuid.uuid4().hex, uuid.uuid4().hex
    _page(owner, outline, 1)
    lecture._sync_material("someone-else", outline, 1, "关键路径法", SECTIONS)
    assert _text(f"v2-outline-{outline}-page-1") == "关键路径法\n要点一\n要点二"
    lecture._sync_material(owner, outline, 9, "关键路径法", SECTIONS)  # 没有这一页：不报错
