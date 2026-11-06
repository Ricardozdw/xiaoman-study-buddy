"""Original PDFs in local development or an existing private Supabase bucket.

Only server-generated file IDs and a hash of the authenticated user enter paths.
In cloud mode the original is mirrored to Supabase before a successful save;
the local PDF is a parser cache. Durable processing state stays local for now.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from app import db
from app.study.materials import cloud_storage
from app.study.materials.errors import MaterialError

MAX_FILE_BYTES = 20 * 1024 * 1024
PATH_PREFIX = "materials/"


def _directory(user_id: str) -> Path:
    owner = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    return db.DATA_DIR / "materials" / owner


def _path(user_id: str, file_id: str, extension: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", file_id):
        raise ValueError("Invalid server file ID")
    return _directory(user_id) / f"{file_id}.{extension}"


def raw_path(user_id: str, file_id: str) -> Path:
    return _path(user_id, file_id, "pdf")


def storage_key(user_id: str, file_id: str) -> str:
    return str(raw_path(user_id, file_id).relative_to(db.DATA_DIR))


def provider_name() -> str:
    return "supabase" if cloud_storage.configured() is not None else "local"


def _cache_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.stem}.{uuid.uuid4().hex}.part")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def save_bytes(user_id: str, file_id: str, content: bytes) -> str:
    key = storage_key(user_id, file_id)
    config = cloud_storage.configured()
    if config is not None:
        cloud_storage.upload(config, key, content)
    try:
        _cache_bytes(raw_path(user_id, file_id), content)
    except OSError:
        raise MaterialError("storage_unavailable", "文件暂时无法保存，请稍后重试", 503) from None
    return key


def ensure_raw_file(user_id: str, file_id: str) -> Path:
    """Return the parser cache, restoring it privately from cloud if needed.

    The caller must verify the database file owner before calling this function.
    raw_path remains a pure path helper; reading status never downloads a PDF.
    """
    path = raw_path(user_id, file_id)
    config = cloud_storage.configured()
    if path.is_file():
        return path
    if config is None:
        raise MaterialError("original_missing", "没有找到已保存的 PDF 原文件，请重新上传", 404)
    content = cloud_storage.download(config, storage_key(user_id, file_id), max_bytes=MAX_FILE_BYTES)
    try:
        _cache_bytes(path, content)
    except OSError:
        raise MaterialError("storage_unavailable", "原文件暂时无法恢复到本机，请稍后重试", 503) from None
    return path


def raw_available(user_id: str, file_id: str) -> bool:
    """Check recovery availability without downloading the PDF."""
    path = raw_path(user_id, file_id)
    config = cloud_storage.configured()
    if path.is_file():
        return True
    return config is not None and cloud_storage.exists(config, storage_key(user_id, file_id))


def read_state(user_id: str, file_id: str) -> dict[str, Any]:
    try:
        value = json.loads(_path(user_id, file_id, "json").read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(user_id: str, file_id: str, state: dict[str, Any]) -> None:
    path = _path(user_id, file_id, "json")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{file_id}.{uuid.uuid4().hex}.part")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
