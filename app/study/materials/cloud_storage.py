"""Server-only access to an existing private Supabase Storage bucket.

Official REST conventions:
https://supabase.com/docs/guides/storage/uploads/standard-uploads
https://supabase.com/docs/guides/storage/serving/downloads
https://supabase.com/docs/guides/storage/security/access-control

No public URLs, bucket creation, client-side keys, or provider response bodies
are exposed. File keys are supplied by storage.py, never by request filenames.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from urllib.parse import quote, urlsplit

import httpx

from app.study.materials.errors import MaterialError

METADATA_LIMIT = 64 * 1024
TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0)


@dataclass(frozen=True)
class StorageConfig:
    url: str
    bucket: str
    service_key: str = field(repr=False)

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.service_key}", "apikey": self.service_key}


def _configuration_error() -> MaterialError:
    return MaterialError(
        "storage_configuration_error",
        "云存储配置不完整或不正确，请在后端配置项目地址、服务密钥和私有存储桶",
        503,
    )


def configured() -> StorageConfig | None:
    """No URL/key means local development; partial settings never silently fall back."""
    url = (os.getenv("SUPABASE_URL") or "").strip()
    key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    explicit_bucket = (os.getenv("SUPABASE_STORAGE_BUCKET") or "").strip()
    bucket = explicit_bucket or "study-materials"
    if not url and not key and not explicit_bucket:
        return None
    if not url or not key or not bucket or not key.isascii() or any(char.isspace() for char in key):
        raise _configuration_error()
    try:
        parsed = urlsplit(url)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if (
            not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or "?" in url
            or "#" in url
            or parsed.path not in ("", "/")
            or parsed.scheme not in ("https", "http")
            or (parsed.scheme == "http" and not local)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", bucket)
        ):
            raise ValueError("invalid settings")
        # Force port parsing too; an invalid port must not reach HTTP error logs.
        parsed.port
    except (TypeError, ValueError):
        raise _configuration_error() from None
    return StorageConfig(url=url.rstrip("/"), bucket=bucket, service_key=key)


def _client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, follow_redirects=False, trust_env=False)


def _failure() -> MaterialError:
    return MaterialError("cloud_storage_unavailable", "云存储暂时无法访问，请稍后重试", 502)


def _read_bounded(response: httpx.Response, maximum: int) -> bytes:
    raw_length = response.headers.get("Content-Length")
    if raw_length:
        try:
            if int(raw_length) > maximum:
                raise MaterialError("cloud_response_too_large", "云存储返回的文件超过本次允许的大小", 502)
        except ValueError:
            raise _failure() from None
    content = bytearray()
    for chunk in response.iter_bytes(chunk_size=64 * 1024):
        if len(content) + len(chunk) > maximum:
            raise MaterialError("cloud_response_too_large", "云存储返回的文件超过本次允许的大小", 502)
        content.extend(chunk)
    return bytes(content)


def _check_private_bucket(client: httpx.Client, config: StorageConfig) -> None:
    with client.stream("GET", f"{config.url}/storage/v1/bucket/{quote(config.bucket, safe='')}", headers=config.headers()) as response:
        if response.status_code != 200:
            raise _failure()
        try:
            metadata = json.loads(_read_bounded(response, METADATA_LIMIT))
        except (UnicodeDecodeError, ValueError):
            raise _failure() from None
    if not isinstance(metadata, dict) or metadata.get("public") is not False:
        raise MaterialError("private_bucket_required", "请为课件配置私有存储桶，当前存储桶无法确认是私有的", 503)


def _object_url(config: StorageConfig, key: str, *, authenticated: bool = False) -> str:
    # A second guard keeps accidental path changes from escaping materials/.
    if not re.fullmatch(r"materials/[a-f0-9]{64}/[a-f0-9]{32}\.pdf", key):
        raise MaterialError("invalid_storage_key", "课件存储位置不正确", 500)
    route = "object/authenticated" if authenticated else "object"
    return f"{config.url}/storage/v1/{route}/{quote(config.bucket, safe='')}/{quote(key, safe='/')}"


def upload(config: StorageConfig, key: str, content: bytes) -> None:
    url = _object_url(config, key)
    try:
        with _client() as client:
            _check_private_bucket(client, config)
            headers = {**config.headers(), "Content-Type": "application/pdf", "x-upsert": "true"}
            with client.stream("POST", url, headers=headers, content=content) as response:
                if not 200 <= response.status_code < 300:
                    raise _failure()
                _read_bounded(response, METADATA_LIMIT)
    except httpx.HTTPError:
        raise _failure() from None


def download(config: StorageConfig, key: str, *, max_bytes: int) -> bytes:
    url = _object_url(config, key, authenticated=True)
    try:
        with _client() as client:
            _check_private_bucket(client, config)
            with client.stream("GET", url, headers=config.headers()) as response:
                if response.status_code == 404:
                    raise MaterialError("original_missing", "没有找到已保存的 PDF 原文件，请重新上传", 404)
                if response.status_code != 200:
                    raise _failure()
                content = _read_bounded(response, max_bytes)
    except httpx.HTTPError:
        raise _failure() from None
    if not content or b"%PDF-" not in content[:1024]:
        raise MaterialError("invalid_cloud_original", "云存储中的原文件无法识别为 PDF，请重新上传", 502)
    return content


def exists(config: StorageConfig, key: str) -> bool:
    url = _object_url(config, key, authenticated=True)
    try:
        with _client() as client:
            _check_private_bucket(client, config)
            response = client.head(url, headers=config.headers())
            if response.status_code == 404:
                return False
            if response.status_code != 200:
                raise _failure()
            return True
    except httpx.HTTPError:
        raise _failure() from None
