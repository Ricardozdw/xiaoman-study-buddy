"""Public, content-free errors for the materials API."""

from __future__ import annotations


class MaterialError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


class MaterialNotFound(MaterialError):
    def __init__(self):
        super().__init__("not_found", "没有找到这份资料", 404)
