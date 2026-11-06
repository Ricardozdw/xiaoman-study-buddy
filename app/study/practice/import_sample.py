"""本地公开样例准备工具，不替代资料线正式上传接口，不调用模型。"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import select

from app.data_access import user_scope
from app.data_access.session import SessionLocal
from app.study.common.db import ensure_schema
from app.study.common.models import MaterialPage, StudyFile


def import_sample(user_id: str, pdf_path: Path, *, display_name: str = "") -> dict:
    raw = pdf_path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    reader = PdfReader(pdf_path)
    if getattr(reader, "is_encrypted", False):
        raise ValueError("请先移除 PDF 密码后再上传")
    if len(reader.pages) > 100:
        raise ValueError("请把资料拆成每讲不超过 100 页的 PDF")
    pages = [{"page": i + 1, "text": p.extract_text() or ""} for i, p in enumerate(reader.pages)]
    if not pages or not any(p["text"].strip() for p in pages):
        raise ValueError("讲义没有可提取的文字；本测试只支持文字版 PDF")
    if sum(len(p["text"]) for p in pages) > 100000:
        raise ValueError("这份资料文字太多，请拆成较小的讲次后上传")
    from app.db import DATA_DIR
    folder = DATA_DIR / "practice" / "samples" / sha[:16]
    folder.mkdir(parents=True, exist_ok=True)
    copied = folder / "source.pdf"
    if not copied.exists():
        shutil.copy2(pdf_path, copied)
    if hashlib.sha256(copied.read_bytes()).hexdigest() != sha:
        raise ValueError("本地副本与原件不一致")
    lecture_id = "ml-basics-" + sha[:12]
    file_id = "sample-" + hashlib.sha256(f"{user_id}:{sha}".encode()).hexdigest()[:40]
    with user_scope(user_id):
        ensure_schema()
        with SessionLocal() as session:
            existing = session.scalar(select(StudyFile).where(StudyFile.id == file_id, StudyFile.user_id == user_id))
            if existing is None:
                session.add(StudyFile(id=file_id, user_id=user_id, filename=display_name or pdf_path.name, mime="application/pdf",
                                      storage_path=str(copied), sha256=sha, parse_status="ready", lecture_id=lecture_id))
                for page in pages:
                    session.add(MaterialPage(id=f"{file_id}-p{page['page']}", user_id=user_id,
                                              lecture_id=lecture_id, file_id=file_id,
                                              page_no=page["page"], text=page["text"]))
                session.commit()
            stored = session.scalars(select(MaterialPage).where(MaterialPage.user_id == user_id,
                                      MaterialPage.lecture_id == lecture_id).order_by(MaterialPage.page_no)).all()
            if [(p.page_no, p.text) for p in stored] != [(p["page"], p["text"]) for p in pages]:
                raise ValueError("资料页读回核对失败")
    manifest = {"lecture_id": lecture_id, "pages": len(pages), "sha256": sha,
                "local_copy": str(copied), "original_path": str(pdf_path.resolve()),
                "characters": sum(len(p["text"]) for p in pages), "model_called": False,
                "filename": display_name or pdf_path.name, "reused": existing is not None}
    (folder / "source.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="给本机测试会话导入一份学习 PDF，不调用模型")
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--user-id", required=True, help="本机 /api/session 返回的会话身份")
    args = parser.parse_args()
    print(json.dumps(import_sample(args.user_id, args.pdf), ensure_ascii=False, indent=2))
