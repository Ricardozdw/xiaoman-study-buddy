"""取资料内容的替换口。问答、练习只调用这里。

现在：返回某一讲的全文，按页，带页码。
以后换知识库：只改这个函数，改成返回检索到的片段，别的线不用动。
"""

from __future__ import annotations

from sqlalchemy import select

from app.data_access.session import SessionLocal
from app.study.common.db import ensure_schema
from app.study.common.models import MaterialPage, StudyFile
from app.study.materials import storage
from app.study.materials.errors import MaterialError, MaterialNotFound

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


def _legacy_pages(session, user_id: str, lecture: str) -> list[dict]:
    """Read main's pre-upload page records without confusing seed data with PDF.

    QA already stored authoritative MaterialPage rows before upload metadata
    existed. Keep that contract, but choose one file group rather than joining
    multiple revisions. Managed uploads are resolved before this fallback.
    """
    rows = session.scalars(select(MaterialPage).where(
        MaterialPage.user_id == user_id, MaterialPage.lecture_id == lecture,
    ).order_by(MaterialPage.page_no, MaterialPage.id)).all()
    groups: dict[str, list[MaterialPage]] = {}
    for row in rows:
        groups.setdefault(row.file_id or "", []).append(row)
    if not groups:
        return []
    files = session.scalars(select(StudyFile).where(
        StudyFile.user_id == user_id, StudyFile.lecture_id == lecture,
        StudyFile.id.in_(groups),
    ).order_by(StudyFile.created_at.desc(), StudyFile.id.desc())).all()
    by_id = {row.id: row for row in files}
    # Known completed versions first; imported rows without file metadata remain
    # compatible with main. Failed/incomplete known versions cannot be sources.
    order = [row.id for row in files if row.parse_status in ("parsed", "ready")]
    order += [key for key in sorted(groups) if key not in by_id]
    candidates = []
    sample = [(item["page"], item["text"]) for item in SAMPLE_PAGES]
    for key in order:
        group = groups[key]
        metadata = by_id.get(key)
        mocked = ([(row.page_no, row.text) for row in group] == sample
                  or bool(metadata and metadata.storage_path.startswith("local://") and not metadata.sha256))
        candidates.append((key, group, mocked))
    if not candidates:
        return []
    key, chosen, mocked = next((item for item in candidates if not item[2]), candidates[0])
    return [
        {"lecture_id": lecture, "page": row.page_no, "text": row.text,
         **({"file_id": key} if key else {}), "mock": mocked,
         **({"sample": True} if mocked else {})}
        for row in chosen
    ]


def fetch_lecture_pages(user_id: str, lecture_id: str, *, file_id: str | None = None) -> list[dict]:
    """Read one successful file version; never mix pages from multiple uploads.

Main's existing MaterialPage imports remain readable. Only the foundation's
explicit lec-6 sample retains a labelled fallback when no stored pages exist.
An unknown lecture or a failed real upload must not become sample content.
"""
    ensure_schema()
    lecture = (lecture_id or SAMPLE_LECTURE_ID).strip() or SAMPLE_LECTURE_ID
    with SessionLocal() as session:
        statement = select(StudyFile).where(
            StudyFile.user_id == user_id,
            StudyFile.lecture_id == lecture,
            StudyFile.storage_path.startswith(storage.PATH_PREFIX),
        )
        if file_id:
            statement = statement.where(StudyFile.id == file_id)
        real_files = session.scalars(statement.order_by(StudyFile.created_at.desc(), StudyFile.id.desc())).all()
        if file_id and not real_files:
            raise MaterialNotFound()
        successful = next((row for row in real_files if row.parse_status in ("parsed", "ready")), None)
        if successful is not None:
            state = storage.read_state(user_id, successful.id)
            source_id = state.get("duplicate_of") or successful.id
            source = session.scalar(select(StudyFile).where(
                StudyFile.id == source_id,
                StudyFile.user_id == user_id,
                StudyFile.lecture_id == lecture,
                StudyFile.sha256 == successful.sha256,
                StudyFile.parse_status.in_(("parsed", "ready")),
            ))
            if source is None:
                return []
            rows = session.scalars(select(MaterialPage).where(
                MaterialPage.user_id == user_id, MaterialPage.file_id == source_id,
                MaterialPage.lecture_id == lecture,
            ).order_by(MaterialPage.page_no)).all()
            return [
                {"lecture_id": lecture, "file_id": successful.id, "page": row.page_no, "text": row.text, "mock": False}
                for row in rows
            ]
        if real_files:
            if file_id:
                raise MaterialError("source_not_ready", "这份 PDF 的正文还没有读取完成", 409)
            return []
        legacy = _legacy_pages(session, user_id, lecture)
        if legacy:
            return legacy
        if lecture != SAMPLE_LECTURE_ID:
            return []
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
