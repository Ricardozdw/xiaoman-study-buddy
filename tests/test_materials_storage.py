"""Private Storage contract without making any network requests."""

from pathlib import Path

import httpx
import pytest

from app.study.materials import cloud_storage, storage
from app.study.materials.errors import MaterialError
from tests.materials_pdf_helpers import pdf_bytes

FILE_ID = 'a' * 32
SERVICE_KEY = 'storage-test-service-key-do-not-log'


@pytest.fixture(autouse=True)
def local_storage(monkeypatch, tmp_path):
    from app import db
    for name in ('SUPABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY', 'SUPABASE_STORAGE_BUCKET'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(db, 'DATA_DIR', tmp_path)


def configure(monkeypatch, handler):
    monkeypatch.setenv('SUPABASE_URL', 'https://project.example.test')
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', SERVICE_KEY)
    # Deliberately omit the bucket setting to verify its documented default.
    client = httpx.Client
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(cloud_storage, '_client', lambda: client(transport=transport, follow_redirects=False))


def private_bucket(request):
    assert request.headers['Authorization'] == f'Bearer {SERVICE_KEY}'
    assert request.headers['apikey'] == SERVICE_KEY
    assert request.url.path == '/storage/v1/bucket/study-materials'
    return httpx.Response(200, json={'id': 'study-materials', 'public': False})


def test_local_adapter_retains_safe_paths_and_state():
    content = pdf_bytes('Local PDF.')
    key = storage.save_bytes('owner/../../name', FILE_ID, content)
    assert key.startswith('materials/') and key.endswith(f'/{FILE_ID}.pdf')
    assert 'owner' not in key and '..' not in key
    assert storage.provider_name() == 'local'
    assert storage.raw_available('owner/../../name', FILE_ID)
    assert storage.ensure_raw_file('owner/../../name', FILE_ID).read_bytes() == content
    storage.write_state('owner/../../name', FILE_ID, {'processed_pages': 1})
    assert storage.read_state('owner/../../name', FILE_ID) == {'processed_pages': 1}
    assert not storage.raw_available('different-user', FILE_ID)


@pytest.mark.parametrize('settings', [
    {'SUPABASE_URL': 'https://project.example.test'},
    {'SUPABASE_SERVICE_ROLE_KEY': SERVICE_KEY},
    {'SUPABASE_STORAGE_BUCKET': 'course-files'},
    {'SUPABASE_URL': 'http://remote.example.test', 'SUPABASE_SERVICE_ROLE_KEY': SERVICE_KEY},
    {'SUPABASE_URL': 'https://username:password@project.example.test', 'SUPABASE_SERVICE_ROLE_KEY': SERVICE_KEY},
    {'SUPABASE_URL': 'https://project.example.test?secret=bad', 'SUPABASE_SERVICE_ROLE_KEY': SERVICE_KEY},
    {'SUPABASE_URL': 'https://project.example.test#', 'SUPABASE_SERVICE_ROLE_KEY': SERVICE_KEY},
    {'SUPABASE_URL': 'https://project.example.test', 'SUPABASE_SERVICE_ROLE_KEY': 'invalid\ncredential'},
    {'SUPABASE_URL': 'https://project.example.test', 'SUPABASE_SERVICE_ROLE_KEY': SERVICE_KEY, 'SUPABASE_STORAGE_BUCKET': '../private'},
])
def test_partial_or_unsafe_configuration_fails_without_silent_local_save(monkeypatch, settings):
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(MaterialError) as error:
        storage.save_bytes('owner', FILE_ID, pdf_bytes('Never silently local.'))
    assert error.value.code == 'storage_configuration_error'
    assert SERVICE_KEY not in str(error.value)
    assert not storage.raw_path('owner', FILE_ID).exists()


def test_cloud_upload_uses_server_credentials_and_owner_key_then_caches(monkeypatch):
    content = pdf_bytes('A real original.')
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == 'GET':
            return private_bucket(request)
        assert request.method == 'POST'
        assert request.url.path == '/storage/v1/object/study-materials/' + storage.storage_key('owner', FILE_ID)
        assert request.headers['Authorization'] == f'Bearer {SERVICE_KEY}'
        assert request.headers['apikey'] == SERVICE_KEY
        assert request.headers['Content-Type'] == 'application/pdf'
        assert request.headers['x-upsert'] == 'true'
        assert request.content == content
        return httpx.Response(200, json={'Key': 'study-materials/' + storage.storage_key('owner', FILE_ID)})

    configure(monkeypatch, handle)
    assert storage.provider_name() == 'supabase'
    storage.save_bytes('owner', FILE_ID, content)
    assert storage.raw_path('owner', FILE_ID).read_bytes() == content
    assert len(requests) == 2
    assert SERVICE_KEY not in repr(cloud_storage.configured())


def test_cloud_original_is_restored_via_authenticated_path_without_reupload(monkeypatch):
    content = pdf_bytes('Restored original.')
    requests = []

    def handle(request):
        requests.append(request)
        if request.url.path.startswith('/storage/v1/bucket/'):
            return private_bucket(request)
        assert request.method == 'GET'
        assert request.url.path == '/storage/v1/object/authenticated/study-materials/' + storage.storage_key('owner', FILE_ID)
        assert request.headers['Authorization'] == f'Bearer {SERVICE_KEY}'
        return httpx.Response(200, content=content, headers={'Content-Type': 'application/pdf'})

    configure(monkeypatch, handle)
    restored = storage.ensure_raw_file('owner', FILE_ID)
    assert restored.read_bytes() == content
    assert len(requests) == 2
    # Further parsing uses the cache and makes no cloud calls.
    assert storage.ensure_raw_file('owner', FILE_ID) == restored
    assert len(requests) == 2


def test_private_bucket_is_required_before_original_can_be_uploaded(monkeypatch):
    seen = []

    def handle(request):
        seen.append(request.method)
        return httpx.Response(200, json={'id': 'study-materials', 'public': True})

    configure(monkeypatch, handle)
    with pytest.raises(MaterialError) as error:
        storage.save_bytes('owner', FILE_ID, pdf_bytes('Private original.'))
    assert error.value.code == 'private_bucket_required'
    assert seen == ['GET']
    assert not storage.raw_path('owner', FILE_ID).exists()


@pytest.mark.parametrize('status', [401, 403, 429, 500, 307])
def test_cloud_errors_are_explicit_and_never_reflect_provider_secrets(monkeypatch, status):
    seen = []

    def handle(request):
        seen.append(str(request.url))
        if request.url.path.startswith('/storage/v1/bucket/'):
            return private_bucket(request)
        return httpx.Response(status, text=f'Provider echo: {SERVICE_KEY}', headers={'Location': 'https://other.example.test/collect'})

    configure(monkeypatch, handle)
    with pytest.raises(MaterialError) as error:
        storage.save_bytes('owner', FILE_ID, pdf_bytes('Original.'))
    assert error.value.code == 'cloud_storage_unavailable'
    assert SERVICE_KEY not in str(error.value)
    assert not any('other.example.test' in url for url in seen)
    assert not storage.raw_path('owner', FILE_ID).exists()


def test_transport_failure_does_not_disclose_exception_details(monkeypatch):
    def handle(request):
        raise httpx.ConnectError(f'Connection diagnostic contains {SERVICE_KEY}', request=request)

    configure(monkeypatch, handle)
    with pytest.raises(MaterialError) as error:
        storage.save_bytes('owner', FILE_ID, pdf_bytes('Original.'))
    assert error.value.code == 'cloud_storage_unavailable'
    assert SERVICE_KEY not in str(error.value)


def test_cloud_download_is_size_bounded_and_does_not_publish_partial_cache(monkeypatch):
    def handle(request):
        if request.url.path.startswith('/storage/v1/bucket/'):
            return private_bucket(request)
        return httpx.Response(200, content=b'%PDF-' + b'x' * 100)

    configure(monkeypatch, handle)
    monkeypatch.setattr(storage, 'MAX_FILE_BYTES', 50)
    with pytest.raises(MaterialError) as error:
        storage.ensure_raw_file('owner', FILE_ID)
    assert error.value.code == 'cloud_response_too_large'
    assert not storage.raw_path('owner', FILE_ID).exists()


def test_missing_original_and_invalid_cloud_pdf_fail_clearly(monkeypatch):
    def handle(request):
        if request.url.path.startswith('/storage/v1/bucket/'):
            return private_bucket(request)
        return httpx.Response(404)

    configure(monkeypatch, handle)
    assert storage.raw_available('owner', FILE_ID) is False
    with pytest.raises(MaterialError) as error:
        storage.ensure_raw_file('owner', FILE_ID)
    assert error.value.code == 'original_missing'
    assert not storage.raw_path('owner', FILE_ID).exists()


def test_invalid_cloud_original_is_not_cached(monkeypatch):
    def handle(request):
        if request.url.path.startswith('/storage/v1/bucket/'):
            return private_bucket(request)
        return httpx.Response(200, content=b'<html>not a PDF</html>')

    configure(monkeypatch, handle)
    with pytest.raises(MaterialError) as error:
        storage.ensure_raw_file('owner', FILE_ID)
    assert error.value.code == 'invalid_cloud_original'
    assert not storage.raw_path('owner', FILE_ID).exists()


def test_cloud_credentials_and_owner_id_never_enter_local_state(monkeypatch):
    def handle(request):
        if request.url.path.startswith('/storage/v1/bucket/'):
            return private_bucket(request)
        return httpx.Response(200, json={})

    configure(monkeypatch, handle)
    storage.save_bytes('confidential-owner-name', FILE_ID, pdf_bytes('Original.'))
    storage.write_state('confidential-owner-name', FILE_ID, {'parse_status': 'uploaded'})
    state = storage.read_state('confidential-owner-name', FILE_ID)
    assert state == {'parse_status': 'uploaded'}
    from app import db
    assert all(SERVICE_KEY not in path.read_text(errors='ignore') for path in Path(db.DATA_DIR).rglob('*.json'))
