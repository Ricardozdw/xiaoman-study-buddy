"""Extract real text, preserving 1-based physical PDF page numbers."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from pypdf import PdfReader

from app.study.materials.errors import MaterialError

MAX_PAGES = 200
MAX_TEXT_CHARACTERS = 1_000_000


def extract_pages(path: Path, on_progress: Callable[[int, int], None]) -> list[dict]:
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise MaterialError("encrypted_pdf", "这份 PDF 有密码保护，请先解除保护再上传")
        count = len(reader.pages)
        if not count:
            raise MaterialError("empty_pdf", "这份 PDF 没有页面，请换一份资料")
        if count > MAX_PAGES:
            raise MaterialError("too_many_pages", f"请上传不超过 {MAX_PAGES} 页的 PDF")
        on_progress(0, count)
        result = []
        characters = 0
        for number, page in enumerate(reader.pages, 1):
            text = (page.extract_text() or "").replace("\x00", "")
            characters += len(text)
            if characters > MAX_TEXT_CHARACTERS:
                raise MaterialError("too_much_text", "资料文字过多，请按讲拆分后上传")
            result.append({"page": number, "text": text})
            on_progress(number, count)
        if not any(item["text"].strip() for item in result):
            raise MaterialError("no_extractable_text", "没有读到文字。这一版只支持文字版 PDF，暂不支持扫描件")
        return result
    except MaterialError:
        raise
    except Exception as exc:
        raise MaterialError("invalid_pdf", "这份 PDF 无法读取，可能已损坏，请换一份或重新导出") from exc
