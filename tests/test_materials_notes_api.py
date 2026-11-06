"""PDF → checked notes → user edits; model calls are isolated test doubles."""

from copy import deepcopy
from html import unescape
import json
import re

import pytest

from app.study.materials import service, summary
from app.study.materials.errors import MaterialError
from tests.materials_pdf_helpers import pdf_bytes
from tests.test_materials_pdf import upload, pages
from tests.test_materials_summary import PAGES, valid_model_output


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setattr(service, 'has_llm', lambda **kwargs: True)
    monkeypatch.setattr(summary, 'has_llm', lambda **kwargs: True)
    calls = []

    def generate(*args, **kwargs):
        calls.append((args, kwargs))
        source = json.loads(unescape(re.search(r"<source>(.*?)</source>", args[1], re.S).group(1)))
        pages = [{"page": page["page"], "text": "".join(part["text"] for part in page["passages"])}
                 for page in source["pages"]]
        return valid_model_output(pages)

    monkeypatch.setattr(summary, 'chat_json', generate)
    return calls


def handout():
    return pdf_bytes(*(item['text'] for item in PAGES))


def test_upload_automatically_generates_verified_notes_and_ready_signal(client, auth, model):
    headers = auth('notes-api-auto')
    file_id, status = upload(client, headers, handout())
    assert status['parse_status'] == status['summary_status'] == 'ready'
    assert status['notes_ready'] and status['note_id']
    note_response = client.get('/api/notes/' + status['note_id'], headers=headers)
    assert note_response.status_code == 200 and note_response.json()['mock'] is False
    note = note_response.json()['data']
    assert note['summary_count'] == 3 and note['point_count'] == 2 and note['term_count'] == 1
    assert note['content']['file_id'] == file_id and note['content']['generation']['model'] == 'test-model'
    assert len(model) == 1
    result = client.get('/api/notes', headers=headers).json()['data']['items']
    assert result[0]['id'] == note['id']


def test_saved_edits_survive_retries_and_duplicate_upload(client, auth, model):
    headers = auth('notes-api-edits')
    file_id, status = upload(client, headers, handout())
    note = client.get('/api/notes/' + status['note_id'], headers=headers).json()['data']
    edited = deepcopy(note['content'])
    edited['summaries'][0]['text'] = 'My personal explanation of the critical path.'
    response = client.patch('/api/notes/' + note['id'], headers=headers, json={'title': 'My project notes', 'content': edited})
    assert response.status_code == 200, response.text
    assert response.json()['data']['edited_by_user'] is True
    client.post(f'/api/files/{file_id}/summarize', headers=headers)
    duplicate_id, duplicate = upload(client, headers, handout(), filename='same.pdf')
    assert duplicate_id != file_id and duplicate['note_id'] == note['id'] and duplicate['notes_ready']
    reloaded = client.get('/api/notes/' + note['id'], headers=headers).json()['data']
    assert reloaded['title'] == 'My project notes'
    assert reloaded['content']['summaries'][0]['text'] == edited['summaries'][0]['text']
    assert len(model) == 1


def test_no_key_and_model_failure_keep_source_and_allow_summary_retry(client, auth, monkeypatch, model):
    headers = auth('notes-api-retry')
    monkeypatch.setattr(service, 'has_llm', lambda **kwargs: False)
    file_id, status = upload(client, headers, handout())
    assert status['parse_status'] == 'parsed' and status['summary_status'] == 'unavailable'
    assert status['note_id'] is None and not status['notes_ready'] and len(model) == 0
    assert 'critical path' in pages(client, headers)[0]['text']
    monkeypatch.setattr(service, 'has_llm', lambda **kwargs: True)
    original = summary.generate_notes

    def unavailable(*args, **kwargs):
        raise MaterialError('model_unavailable', 'Model temporarily unavailable', 502)

    monkeypatch.setattr(summary, 'generate_notes', unavailable)
    client.post(f'/api/files/{file_id}/summarize', headers=headers)
    status = client.get(f'/api/files/{file_id}/status', headers=headers).json()['data']
    assert status['parse_status'] == 'parsed' and status['summary_status'] == 'failed'
    assert pages(client, headers)
    monkeypatch.setattr(summary, 'generate_notes', original)
    client.post(f'/api/files/{file_id}/summarize', headers=headers)
    status = client.get(f'/api/files/{file_id}/status', headers=headers).json()['data']
    assert status['notes_ready'] and status['summary_error'] is None


def test_old_note_citations_use_original_file_version_and_other_user_is_denied(client, auth, model, monkeypatch):
    headers, stranger = auth('notes-api-versions'), auth('notes-api-stranger')
    old_id, old = upload(client, headers, handout())
    monkeypatch.setattr(service, 'has_llm', lambda **kwargs: False)
    upload(client, headers, pdf_bytes('A replacement PDF about a different subject.'))
    assert 'replacement PDF' in pages(client, headers)[0]['text']
    original = client.get(f'/api/lectures/lec-3/pages?file_id={old_id}', headers=headers)
    assert original.status_code == 200 and 'critical path' in original.json()['data']['pages'][0]['text']
    assert client.get(f'/api/lectures/lec-3/pages?file_id={old_id}', headers=stranger).status_code == 404
    assert client.get('/api/notes/' + old['note_id'], headers=stranger).status_code == 404
    note = client.get('/api/notes/' + old['note_id'], headers=headers).json()['data']
    changed = deepcopy(note['content'])
    changed['summaries'][0]['text'] = 'Edited after replacing the lecture PDF.'
    result = client.patch('/api/notes/' + old['note_id'], headers=headers, json={'content': changed})
    assert result.status_code == 200
    changed['summaries'][0]['page'] = 2
    rejected = client.patch('/api/notes/' + old['note_id'], headers=headers, json={'content': changed})
    assert rejected.status_code == 422


def test_notes_ready_automatically_completes_matching_plan_task(client, auth, model):
    headers = auth('notes-api-plan')
    before = client.get('/api/plan/today', headers=headers).json()['data']
    learn = next(item for item in before['tasks'] if item['kind'] == 'learn')
    assert learn['status'] == 'todo'
    _, status = upload(client, headers, handout(), lecture='lec-7')
    assert status['notes_ready']
    after = client.get('/api/plan/today', headers=headers).json()['data']
    assert next(item for item in after['tasks'] if item['id'] == learn['id'])['status'] == 'done'


def test_automatic_summary_handoff_is_pending_before_background_generation(client, auth, monkeypatch):
    original = service.start_summarizing
    observed = []

    def inspect_handoff(user_id, file_id):
        status = service.file_status(user_id, file_id)
        observed.append((status['parse_status'], status['summary_status']))
        return original(user_id, file_id)

    monkeypatch.setattr(service, 'start_summarizing', inspect_handoff)
    _, status = upload(client, auth('notes-api-handoff'), handout())
    assert observed[0] == ('parsed', 'pending')
    assert status['summary_status'] == 'unavailable'
