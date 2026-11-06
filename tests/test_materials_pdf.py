"""Real PDF ingestion, page provenance, failures and owner isolation."""

import pytest

from tests.materials_pdf_helpers import pdf_bytes


def create(client, headers, filename='lecture.pdf'):
    response = client.post('/api/files/upload-url', json={'filename': filename, 'mime': 'application/pdf'}, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()['mock'] is False
    return response.json()['data']['file_id']


def upload(client, headers, content, lecture='lec-3', filename='lecture.pdf'):
    file_id = create(client, headers, filename)
    response = client.put(f'/api/files/{file_id}/raw', content=content, headers={**headers, 'Content-Type': 'application/pdf'})
    assert response.status_code == 200, response.text
    response = client.post(f'/api/files/{file_id}/complete', json={'lecture_id': lecture}, headers=headers)
    assert response.status_code == 200, response.text
    return file_id, client.get(f'/api/files/{file_id}/status', headers=headers).json()['data']


def pages(client, headers, lecture='lec-3'):
    return client.get(f'/api/lectures/{lecture}/pages', headers=headers).json()['data']['pages']


def test_pdf_upload_persists_real_pages_and_complete_is_idempotent(client, auth):
    headers = auth('pdf-real')
    file_id, status = upload(client, headers, pdf_bytes('Critical path is the longest path.', 'Project schedule.'))
    assert status['parse_status'] == 'parsed'
    assert status['processed_pages'] == status['page_count'] == 2
    assert status['error'] is None and status['mock'] is False
    result = pages(client, headers)
    assert [page['page'] for page in result] == [1, 2]
    assert 'longest path' in result[0]['text']
    assert all(page['mock'] is False for page in result)
    client.post(f'/api/files/{file_id}/complete', json={'lecture_id': 'lec-3'}, headers=headers)
    assert pages(client, headers) == result
    listed = client.get('/api/files', headers=headers).json()['data']['items']
    assert any(item['id'] == file_id and item['parse_status'] == 'parsed' for item in listed)


def test_physical_page_numbers_include_blank_pages(client, auth):
    headers = auth('pdf-blank-between')
    _, status = upload(client, headers, pdf_bytes('First page.', None, 'Third page.'))
    assert status['parse_status'] == 'parsed'
    result = pages(client, headers)
    assert [page['page'] for page in result] == [1, 2, 3]
    assert result[1]['text'].strip() == ''
    assert 'Third page' in result[2]['text']


def test_duplicate_file_for_same_lecture_does_not_duplicate_pages(client, auth):
    headers = auth('pdf-deduplicate')
    content = pdf_bytes('One set of pages.')
    upload(client, headers, content)
    _, status = upload(client, headers, content, filename='renamed.pdf')
    assert status['parse_status'] == 'parsed'
    result = pages(client, headers)
    assert len(result) == 1 and 'One set' in result[0]['text']


def test_same_pdf_can_be_assigned_to_a_different_lecture(client, auth):
    headers = auth('pdf-two-lectures')
    content = pdf_bytes('Shared course handout.')
    upload(client, headers, content, lecture='lec-3')
    _, status = upload(client, headers, content, lecture='lec-4')
    assert status['parse_status'] == 'parsed'
    assert pages(client, headers, 'lec-3')[0]['text'] == pages(client, headers, 'lec-4')[0]['text']


def test_new_version_reads_only_one_file_and_failure_keeps_previous_pages(client, auth):
    headers = auth('pdf-replace')
    upload(client, headers, pdf_bytes('Original version.'), filename='old.pdf')
    failed_id, status = upload(client, headers, pdf_bytes(None), filename='empty.pdf')
    assert status['parse_status'] == 'failed'
    assert status['error']['message'] and status['can_retry']
    assert 'Original version' in pages(client, headers)[0]['text']
    upload(client, headers, pdf_bytes('Replacement version.', 'Second replacement page.'), filename='new.pdf')
    result = pages(client, headers)
    assert len(result) == 2
    assert 'Replacement version' in result[0]['text']
    assert all('Original version' not in page['text'] for page in result)


def test_ownership_protects_file_content_status_upload_and_listing(client, auth):
    owner, other = auth('pdf-owner'), auth('pdf-other')
    file_id, _ = upload(client, owner, pdf_bytes('Owner private lecture.'))
    assert client.get(f'/api/files/{file_id}/status', headers=other).status_code == 404
    assert client.put(f'/api/files/{file_id}/raw', content=pdf_bytes('Attack.'), headers={**other, 'Content-Type': 'application/pdf'}).status_code == 404
    assert client.post(f'/api/files/{file_id}/complete', json={'lecture_id': 'lec-3'}, headers=other).status_code == 404
    assert all(item['id'] != file_id for item in client.get('/api/files', headers=other).json()['data']['items'])
    assert all('Owner private lecture' not in page['text'] for page in pages(client, other))
    assert 'Owner private lecture' in pages(client, owner)[0]['text']


def test_empty_upload_is_an_error_not_a_fake_success(client, auth):
    headers = auth('pdf-empty-upload')
    file_id = create(client, headers)
    response = client.put(f'/api/files/{file_id}/raw', content=b'', headers={**headers, 'Content-Type': 'application/pdf'})
    assert 400 <= response.status_code < 500
    response = client.post(f'/api/files/{file_id}/complete', json={'lecture_id': 'lec-3'}, headers=headers)
    assert 400 <= response.status_code < 500


@pytest.mark.parametrize('content', [b'%PDF-1.7\nnot a valid PDF', pdf_bytes(None), pdf_bytes('Secret.', password='test-password')])
def test_unreadable_pdf_has_an_explicit_failure_without_sample_substitution(client, auth, content):
    headers = auth('pdf-unreadable-' + str(len(content)))
    file_id = create(client, headers)
    raw = client.put(f'/api/files/{file_id}/raw', content=content, headers={**headers, 'Content-Type': 'application/pdf'})
    if raw.status_code == 200:
        client.post(f'/api/files/{file_id}/complete', json={'lecture_id': 'lec-9'}, headers=headers)
        status = client.get(f'/api/files/{file_id}/status', headers=headers).json()['data']
        assert status['parse_status'] == 'failed'
        assert status['error']['code'] and status['error']['message']
    else:
        assert 400 <= raw.status_code < 500
    result = pages(client, headers, 'lec-9')
    assert not any('每天最多三件事' in page['text'] for page in result)


def test_missing_lecture_is_not_silently_assigned_to_lecture_six(client, auth):
    headers = auth('pdf-no-lecture')
    file_id = create(client, headers)
    client.put(f'/api/files/{file_id}/raw', content=pdf_bytes('Lecture needs an identifier.'), headers={**headers, 'Content-Type': 'application/pdf'})
    response = client.post(f'/api/files/{file_id}/complete', json={}, headers=headers)
    assert 400 <= response.status_code < 500


def test_parsed_pdf_does_not_claim_ai_notes_or_complete_plan(client, auth):
    headers = auth('pdf-not-ai-ready')
    before = client.get('/api/plan/today', headers=headers).json()['data']
    task = next(task for task in before['tasks'] if task['kind'] == 'learn')
    _, status = upload(client, headers, pdf_bytes('Text extraction completed.'), lecture='lec-7')
    assert status['parse_status'] == 'parsed'
    after = client.get('/api/plan/today', headers=headers).json()['data']
    assert next(item for item in after['tasks'] if item['id'] == task['id'])['status'] == 'todo'


def test_failed_extraction_can_retry_saved_original(client, auth, monkeypatch):
    from app.study.materials import parser
    from app.study.materials.errors import MaterialError

    headers = auth('pdf-retry')
    original = parser.extract_pages

    def transient_failure(path, on_progress):
        raise MaterialError('temporary_error', 'Temporary extraction failure')

    monkeypatch.setattr(parser, 'extract_pages', transient_failure)
    file_id, status = upload(client, headers, pdf_bytes('Retry reads the saved original.'))
    assert status['parse_status'] == 'failed' and status['can_retry']
    monkeypatch.setattr(parser, 'extract_pages', original)
    response = client.post(f'/api/files/{file_id}/complete', json={'lecture_id': 'lec-3'}, headers=headers)
    assert response.status_code == 200
    status = client.get(f'/api/files/{file_id}/status', headers=headers).json()['data']
    assert status['parse_status'] == 'parsed' and status['error'] is None
    assert 'Retry reads the saved original' in pages(client, headers)[0]['text']


def test_duplicate_reuses_saved_pages_without_running_parser(client, auth, monkeypatch):
    from app.study.materials import parser

    headers = auth('pdf-no-extra-parse')
    content = pdf_bytes('Read once and reuse.')
    upload(client, headers, content)

    def forbidden_reparse(path, on_progress):
        pytest.fail('A duplicate PDF should reuse pages instead of parsing again')

    monkeypatch.setattr(parser, 'extract_pages', forbidden_reparse)
    _, status = upload(client, headers, content, filename='duplicate.pdf')
    assert status['parse_status'] == 'parsed' and status['reused']


def test_file_and_page_limits_report_errors(client, auth, monkeypatch):
    from app.study.materials import parser, storage

    headers = auth('pdf-limits')
    content = pdf_bytes('Page one.', 'Page two.')
    file_id = create(client, headers)
    monkeypatch.setattr(storage, 'MAX_FILE_BYTES', len(content) - 1)
    response = client.put(f'/api/files/{file_id}/raw', content=content, headers={**headers, 'Content-Type': 'application/pdf'})
    assert response.status_code == 413
    monkeypatch.setattr(storage, 'MAX_FILE_BYTES', 20 * 1024 * 1024)
    monkeypatch.setattr(parser, 'MAX_PAGES', 1)
    _, status = upload(client, headers, content)
    assert status['parse_status'] == 'failed'
    assert status['error']['code'] == 'too_many_pages'
