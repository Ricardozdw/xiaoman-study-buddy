from pypdf import PdfWriter
from sqlalchemy import select

from app.data_access import user_scope
from app.data_access.session import SessionLocal
from app.study.common.models import MaterialPage
from app.study.practice.import_sample import import_sample


def test_sample_readback_dedup_and_isolation(tmp_path, monkeypatch):
    pdf = tmp_path / "sample.pdf"
    writer = PdfWriter()
    writer.add_blank_page(300, 300)
    writer.write(pdf)
    class Page:
        def extract_text(self): return "机器学习从数据中归纳规律。"
    class Reader:
        def __init__(self, _): self.pages = [Page()]
    monkeypatch.setattr("app.study.practice.import_sample.PdfReader", Reader)
    first = import_sample("sample-a", pdf)
    second = import_sample("sample-a", pdf)
    assert first["lecture_id"] == second["lecture_id"] and first["sha256"] == second["sha256"]
    assert first["reused"] is False and second["reused"] is True
    with user_scope("sample-a"), SessionLocal() as session:
        assert len(session.scalars(select(MaterialPage).where(MaterialPage.user_id == "sample-a",
                                   MaterialPage.lecture_id == first["lecture_id"])).all()) == 1
    with user_scope("sample-b"), SessionLocal() as session:
        assert session.scalars(select(MaterialPage).where(MaterialPage.user_id == "sample-b",
                               MaterialPage.lecture_id == first["lecture_id"])).all() == []
