"""独立练习页的 PDF 测试入口，不修改资料线的正式接口。"""
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.data_access.session import SessionLocal
from app.study.common.db import ensure_schema
from app.study.common.models import MaterialPage, StudyFile
from app.study.practice.import_sample import import_sample
from app.study.practice.service import lock_for

MAX_FILE_BYTES = 20 * 1024 * 1024


def material_list(user_id: str) -> dict:
    ensure_schema()
    with SessionLocal() as session:
        files = session.scalars(select(StudyFile).where(StudyFile.user_id == user_id,
                    StudyFile.id.like("sample-%"), StudyFile.parse_status == "ready")
                    .order_by(StudyFile.created_at.desc())).all()
        items = []
        for f in files:
            pages = session.scalars(select(MaterialPage).where(MaterialPage.user_id == user_id,
                                     MaterialPage.file_id == f.id)).all()
            items.append({"lecture_id": f.lecture_id, "filename": f.filename, "page_count": len(pages),
                          "character_count": sum(len(p.text) for p in pages)})
        return {"items": items}


def _import(user_id: str, path: Path, filename: str):
    with lock_for(user_id):
        result = import_sample(user_id, path, display_name=filename)
    return {"lecture_id": result["lecture_id"], "filename": filename, "page_count": result["pages"],
            "character_count": result["characters"], "reused": result["reused"]}


async def upload(user_id: str, file: UploadFile) -> dict:
    filename = Path((file.filename or "").replace("\\", "/")).name
    try:
        if not filename.lower().endswith(".pdf"):
            raise HTTPException(422, detail={"message": "请选择文字版 PDF 文件"})
        with TemporaryDirectory(prefix="xiaoman-practice-upload-") as folder:
            path = Path(folder) / "source.pdf"
            size = 0
            with path.open("wb") as out:
                while chunk := await file.read(64 * 1024):
                    size += len(chunk)
                    if size > MAX_FILE_BYTES:
                        raise HTTPException(413, detail={"message": "文件超过 20 MB，请拆分后上传"})
                    out.write(chunk)
            with path.open("rb") as incoming:
                header = incoming.read(5)
            if header != b"%PDF-":
                raise HTTPException(422, detail={"message": "文件内容不是可读取的 PDF"})
            try:
                return await run_in_threadpool(_import, user_id, path, filename)
            except ValueError as exc:
                raise HTTPException(422, detail={"message": str(exc)}) from None
            except Exception:
                raise HTTPException(422, detail={"message": "这份 PDF 没能读成功，请检查文件后重试"}) from None
    finally:
        await file.close()
