"""Persistence, provenance and editable note invariants without model calls."""

from copy import deepcopy
import hashlib
import json
import uuid

import pytest
from sqlalchemy import select

from app.data_access.session import SessionLocal
from app.study.common.db import ensure_schema
from app.study.common.models import Chapter, Course, Goal, KnowledgePoint, MaterialPage, Note, StudyFile, _now
from app.study.materials import notes, storage
from app.study.materials.errors import MaterialError
from app.study.materials.summary import source_hash

SOURCE = 'Critical path is the longest path. Schedule work carefully. Project plans have milestones.'


def make_source(user_id, *, text=SOURCE, lecture='lec-3', duplicate_of=None):
    ensure_schema()
    file_id = uuid.uuid4().hex
    digest = hashlib.sha256(text.encode()).hexdigest()
    with SessionLocal() as session:
        session.add(StudyFile(
            id=file_id, user_id=user_id, filename='Original.pdf', mime='application/pdf',
            storage_path=storage.storage_key(user_id, file_id), sha256=digest,
            parse_status='parsed', lecture_id=lecture, created_at=_now(),
        ))
        if duplicate_of is None:
            session.add(MaterialPage(
                id=uuid.uuid4().hex, user_id=user_id, file_id=file_id,
                lecture_id=lecture, page_no=1, text=text,
            ))
        session.commit()
    if duplicate_of is not None:
        storage.write_state(user_id, file_id, {'duplicate_of': duplicate_of})
    return file_id, [{'page': 1, 'text': text, 'mock': False}]


def generated(pages):
    return {
        'title': 'Project planning notes',
        'summaries': [
            {'text': 'Identify the critical path.', 'page': 1, 'quote': 'Critical path'},
            {'text': 'Schedule the work.', 'page': 1, 'quote': 'Schedule work carefully'},
            {'text': 'Track milestones.', 'page': 1, 'quote': 'Project plans have milestones'},
        ],
        'knowledge_points': [
            {'name': 'Critical path', 'explanation': 'The longest route through the project.', 'page': 1, 'quote': 'Critical path is the longest path'},
        ],
        'terms': [{'term': 'Milestone', 'definition': 'A planning checkpoint.', 'page': 1, 'quote': 'Project plans have milestones'}],
        'generation': {'model': 'unit-test-model', 'prompt_name': 'materials.summary', 'prompt_version': 'v1', 'source_hash': source_hash(pages), 'mode': 'live', 'attempts': 1},
    }


def save(user_id, file_id, pages, **kwargs):
    return notes.save_generated(user_id, file_id, kwargs.get('lecture', 'lec-3'), 'Original', generated(pages))


def test_save_generated_creates_real_note_and_knowledge_point_rows(uid):
    file_id, pages = make_source(uid)
    saved = save(uid, file_id, pages)
    assert saved['id'] == 'materials:' + file_id
    assert saved['mock'] is False and not saved['edited_by_user']
    assert saved['summary_count'] == 3 and saved['point_count'] == saved['term_count'] == 1
    assert saved['content']['points'] == [item['text'] for item in saved['content']['summaries']]
    assert notes.get_for_file(uid, file_id) == saved
    assert notes.list_real_notes(uid) == [saved]
    point_id = saved['content']['knowledge_points'][0]['id']
    with SessionLocal() as session:
        point = session.get(KnowledgePoint, point_id)
        assert point.user_id == uid and point.mastery == 0
        assert json.loads(point.source_json)['file_id'] == file_id
        assert json.loads(point.source_json)['page'] == 1


def test_regeneration_reuses_existing_note_and_never_overwrites_user_edits(uid):
    file_id, pages = make_source(uid)
    original = save(uid, file_id, pages)
    content = deepcopy(original['content'])
    content['summaries'][0]['text'] = 'My own planning explanation.'
    edited = notes.update_note(uid, original['id'], content, title='My title')
    assert edited['edited_by_user'] and edited['title'] == 'My title'
    # Even invalid new model output is ignored when a saved note exists.
    again = notes.save_generated(uid, file_id, 'lec-3', 'Overwrite attempt', {})
    assert again == edited
    with SessionLocal() as session:
        assert len(session.scalars(select(KnowledgePoint).where(KnowledgePoint.user_id == uid)).all()) == 1


def test_user_edits_keep_knowledge_point_identity_mastery_and_review_date(uid):
    file_id, pages = make_source(uid)
    original = save(uid, file_id, pages)
    point_id = original['content']['knowledge_points'][0]['id']
    with SessionLocal() as session:
        point = session.get(KnowledgePoint, point_id)
        point.mastery = 76
        point.next_review_on = '2026-12-01'
        session.commit()
    content = deepcopy(original['content'])
    content['knowledge_points'][0]['name'] = 'My critical path label'
    content['knowledge_points'][0]['explanation'] = 'My revised explanation.'
    content['knowledge_points'][0]['id'] = 'forged-client-id'
    content['generation'] = {'model': 'client-forged-model'}
    with pytest.raises(MaterialError) as invalid_identity:
        notes.update_note(uid, original['id'], content)
    assert invalid_identity.value.code == 'notes_identity_conflict'
    content['knowledge_points'][0]['id'] = point_id
    updated = notes.update_note(uid, original['id'], content)
    assert updated['content']['knowledge_points'][0]['id'] == point_id
    assert updated['content']['generation'] == original['content']['generation']
    with SessionLocal() as session:
        point = session.get(KnowledgePoint, point_id)
        assert point.mastery == 76 and point.next_review_on == '2026-12-01'
        assert point.name == 'My critical path label'
        assert point.explanation == 'My revised explanation.'
        assert session.get(KnowledgePoint, 'forged-client-id') is None


def test_edit_validation_uses_original_file_after_lecture_version_changes(uid):
    file_id, pages = make_source(uid)
    original = save(uid, file_id, pages)
    make_source(uid, text='A new lecture version with completely different content.')
    content = deepcopy(original['content'])
    content['terms'][0]['definition'] = 'Edited against the original PDF.'
    assert notes.update_note(uid, original['id'], content)['content']['file_id'] == file_id


@pytest.mark.parametrize('change', ['page', 'quote', 'file'])
def test_invalid_edits_fail_atomically_without_changing_saved_note(uid, change):
    file_id, pages = make_source(uid)
    original = save(uid, file_id, pages)
    content = deepcopy(original['content'])
    if change == 'page':
        content['summaries'][0]['page'] = 2
    elif change == 'quote':
        content['summaries'][0]['quote'] = 'This quote does not exist'
    else:
        content['file_id'] = 'b' * 32
    with pytest.raises(MaterialError):
        notes.update_note(uid, original['id'], content)
    assert notes.get_note(uid, original['id']) == original


def test_notes_cannot_be_read_or_edited_across_users(uid):
    file_id, pages = make_source(uid)
    original = save(uid, file_id, pages)
    assert notes.get_note('other-owner', original['id']) is None
    assert notes.list_real_notes('other-owner') == []
    with pytest.raises(MaterialError) as error:
        notes.update_note('other-owner', original['id'], original['content'])
    assert error.value.http_status == 404
    assert notes.get_for_file('other-owner', file_id) is None


def test_duplicate_upload_points_to_one_canonical_note(uid):
    file_id, pages = make_source(uid)
    original = save(uid, file_id, pages)
    duplicate_id, _ = make_source(uid, duplicate_of=file_id)
    assert notes.get_for_file(uid, duplicate_id) == original
    assert notes.save_generated(uid, duplicate_id, 'lec-3', 'Duplicate', generated(pages)) == original
    assert len(notes.list_real_notes(uid)) == 1


def test_notes_larger_than_legacy_twenty_thousand_characters_remain_valid_json(uid):
    file_id, pages = make_source(uid)
    output = generated(pages)
    output['knowledge_points'] = [
        {'name': f'Topic {index}', 'explanation': 'y' * 600, 'page': 1, 'quote': 'Critical path'}
        for index in range(20)
    ]
    output['terms'] = [
        {'term': f'Term {index}', 'definition': 'z' * 600, 'page': 1, 'quote': 'Critical path'}
        for index in range(20)
    ]
    saved = notes.save_generated(uid, file_id, 'lec-3', 'Original', output)
    with SessionLocal() as session:
        stored = session.get(Note, saved['id'])
        assert len(stored.content_json) > 20_000
        assert json.loads(stored.content_json)['terms'][-1]['definition'] == 'z' * 600
    assert notes.get_note(uid, saved['id'])['term_count'] == 20


def test_saved_notes_cannot_bypass_outbound_guard_on_read_or_edit(uid, monkeypatch):
    file_id, pages = make_source(uid)
    original = save(uid, file_id, pages)
    monkeypatch.setattr(notes, 'guard_text', lambda *args, **kwargs: 'blocked by guard')
    with pytest.raises(MaterialError) as error:
        notes.get_note(uid, original['id'])
    assert error.value.code == 'notes_guard_blocked'
    with pytest.raises(MaterialError):
        notes.update_note(uid, original['id'], original['content'])


def test_guard_unavailability_prevents_any_note_or_point_write(uid, monkeypatch):
    file_id, pages = make_source(uid)

    def unavailable(*args, **kwargs):
        raise RuntimeError('Internal guard diagnostic must not leak')

    monkeypatch.setattr(notes, 'guard_text', unavailable)
    with pytest.raises(MaterialError) as error:
        save(uid, file_id, pages)
    assert error.value.code == 'notes_guard_unavailable'
    assert 'diagnostic' not in str(error.value)
    with SessionLocal() as session:
        assert session.scalar(select(Note).where(Note.user_id == uid)) is None
        assert session.scalar(select(KnowledgePoint).where(KnowledgePoint.user_id == uid)) is None


def test_generation_source_hash_and_lecture_must_match_original(uid):
    file_id, pages = make_source(uid)
    output = generated(pages)
    output['generation']['source_hash'] = '0' * 64
    with pytest.raises(MaterialError) as error:
        notes.save_generated(uid, file_id, 'lec-3', 'Original', output)
    assert error.value.code == 'notes_source_mismatch'
    with pytest.raises(MaterialError) as error:
        notes.save_generated(uid, file_id, 'lec-99', 'Original', generated(pages))
    assert error.value.code == 'lecture_conflict'


def test_get_for_file_returns_none_before_source_is_ready(uid):
    file_id, _ = make_source(uid)
    with SessionLocal() as session:
        row = session.get(StudyFile, file_id)
        row.parse_status = 'uploaded'
        session.commit()
    assert notes.get_for_file(uid, file_id) is None


def test_new_chapter_is_listed_without_fabricating_a_course_or_goal(uid):
    file_id, pages = make_source(uid, lecture='lec-11')
    saved = save(uid, file_id, pages, lecture='lec-11')
    with SessionLocal() as session:
        chapter = session.scalar(select(Chapter).where(Chapter.user_id == uid, Chapter.lecture_id == 'lec-11'))
        assert chapter is not None and chapter.course_id == ''
        assert '11' in chapter.title and saved['title'] in chapter.title
        assert session.scalar(select(Course).where(Course.user_id == uid)) is None
        assert session.scalar(select(Goal).where(Goal.user_id == uid)) is None


def test_chapter_uses_first_owned_course_and_keeps_existing_title(uid):
    ensure_schema()
    with SessionLocal() as session:
        session.add_all([
            Course(id=uuid.uuid4().hex, user_id='foreign-course-owner', title='Foreign', sort_order=-10),
            Course(id='notes-course-' + uid, user_id=uid, title='Owned', sort_order=1),
        ])
        session.commit()
    file_id, pages = make_source(uid, lecture='lec-12')
    save(uid, file_id, pages, lecture='lec-12')
    with SessionLocal() as session:
        chapter = session.scalar(select(Chapter).where(Chapter.user_id == uid, Chapter.lecture_id == 'lec-12'))
        assert chapter.course_id == 'notes-course-' + uid
        chapter.title = 'My saved lecture title'
        session.commit()
    second_file, second_pages = make_source(uid, lecture='lec-12')
    save(uid, second_file, second_pages, lecture='lec-12')
    with SessionLocal() as session:
        chapters = session.scalars(select(Chapter).where(Chapter.user_id == uid, Chapter.lecture_id == 'lec-12')).all()
        assert len(chapters) == 1 and chapters[0].title == 'My saved lecture title'


def test_phone_shaped_digits_inside_server_file_identifier_are_not_contact_data(uid):
    ensure_schema()
    file_id = '4c8623d2a89b4be89ae3e17487176043'
    with SessionLocal() as session:
        session.add(StudyFile(
            id=file_id, user_id=uid, filename='Original.pdf', mime='application/pdf',
            storage_path=storage.storage_key(uid, file_id), sha256=hashlib.sha256(SOURCE.encode()).hexdigest(),
            parse_status='parsed', lecture_id='lec-3', created_at=_now(),
        ))
        session.add(MaterialPage(id=uuid.uuid4().hex, user_id=uid, file_id=file_id, lecture_id='lec-3', page_no=1, text=SOURCE))
        session.commit()
    saved = save(uid, file_id, [{'page': 1, 'text': SOURCE, 'mock': False}])
    assert saved['content']['file_id'] == file_id


def test_reordering_knowledge_points_cannot_move_learning_history_to_another_concept(uid):
    file_id, pages = make_source(uid)
    output = generated(pages)
    output['knowledge_points'].append({'name': 'Milestones', 'explanation': 'Planning checkpoints.', 'page': 1, 'quote': 'Project plans have milestones'})
    original = notes.save_generated(uid, file_id, 'lec-3', 'Original', output)
    ids = [point['id'] for point in original['content']['knowledge_points']]
    with SessionLocal() as session:
        for point_id, mastery in zip(ids, [10, 90]):
            session.get(KnowledgePoint, point_id).mastery = mastery
        session.commit()
    reordered = deepcopy(original['content'])
    reordered['knowledge_points'].reverse()
    with pytest.raises(MaterialError) as error:
        notes.update_note(uid, original['id'], reordered)
    assert error.value.code == 'notes_identity_conflict'
    assert notes.get_note(uid, original['id']) == original
    with SessionLocal() as session:
        assert [(session.get(KnowledgePoint, point_id).name, session.get(KnowledgePoint, point_id).mastery) for point_id in ids] == [('Critical path', 10), ('Milestones', 90)]
