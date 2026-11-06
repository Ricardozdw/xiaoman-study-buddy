"""Real upload/extraction connects to main's QA contract without a notes model."""

import json
import uuid

import pytest

from app.data_access import user_scope
from app.data_access.session import SessionLocal
from app.study.common.db import ensure_schema
from app.study.common.models import MaterialPage
from app.study.materials import service as materials_service
from app.study.materials.content import SAMPLE_PAGES, fetch_lecture_pages
from app.study.qa import service as qa_service
from tests.materials_pdf_helpers import pdf_bytes
from tests.test_materials_pdf import upload


LECTURE = "uploaded-project-network"
PAGE_ONE = "A project network describes dependencies between activities."
PAGE_THREE = "The critical path is the longest route through the project network."


def frames(response):
    assert response.status_code == 200, response.text
    return [json.loads(line[5:]) for line in response.text.splitlines()
            if line.startswith("data:") and "[DONE]" not in line]


def grounded_qa(monkeypatch):
    seen = []
    monkeypatch.setattr(qa_service, "classify", lambda *_: {"intent": "qa", "mock": False})

    def stream(system, source, **kwargs):
        seen.append(json.loads(source.removeprefix("<source>").removesuffix("</source>")))
        lines = [
            {"type": "scope", "in_material": True},
            {"type": "sentence", "text": "The critical path is the longest project route.",
             "references": [{"page": 3, "quote": PAGE_THREE}]},
        ]
        for item in lines:
            yield {"delta": json.dumps(item) + "\n"}
        yield {"type": "usage", "model": "isolated-qa-test", "mock": False,
               "ok": True, "estimated": False, "prompt_tokens": 20, "completion_tokens": 12}

    monkeypatch.setattr(qa_service, "stream_text", stream)
    return seen


def test_uploaded_pdf_can_be_asked_before_notes_model_is_configured(client, auth, monkeypatch):
    headers = auth("materials-qa-upload")
    monkeypatch.setattr(materials_service, "has_llm", lambda **_: False)
    file_id, status = upload(client, headers, pdf_bytes(PAGE_ONE, None, PAGE_THREE), lecture=LECTURE)
    assert status["parse_status"] == "parsed"
    assert status["summary_status"] == "unavailable" and not status["notes_ready"]
    assert status["summary_error"]["code"] == "model_not_configured"

    material = client.get(f"/api/lectures/{LECTURE}/pages", params={"file_id": file_id}, headers=headers)
    assert material.status_code == 200 and material.json()["mock"] is False
    pages = material.json()["data"]["pages"]
    assert [row["page"] for row in pages] == [1, 2, 3]
    assert not pages[1]["text"].strip()
    assert all(row["mock"] is False and row["file_id"] == file_id for row in pages)
    choices = client.get("/api/qa/lectures", headers=headers).json()
    assert choices["mock"] is False
    assert next(row for row in choices["data"]["items"] if row["id"] == LECTURE)["mock"] is False

    seen = grounded_qa(monkeypatch)
    events = frames(client.post("/api/chat/stream", headers=headers,
                               json={"message": "What is the critical path?", "lecture_id": LECTURE}))
    assert len(seen) == 1
    assert [page["page"] for page in seen[0]["pages"]] == [1, 2, 3]
    assert PAGE_ONE in seen[0]["pages"][0]["text"]
    assert PAGE_THREE in seen[0]["pages"][2]["text"]
    assert next(item for item in events if item.get("type") == "meta")["mock"] is False
    complete = next(item for item in events if item.get("type") == "complete")
    assert complete["ok"] is True and complete["mock"] is False and complete["citation_failures"] == 0
    references = next(item for item in events if item.get("type") == "references")["references"]
    assert references == [{"lecture_id": LECTURE, "page": 3, "quote": PAGE_THREE}]
    assert "【第 3 页】" in "".join(item.get("delta", "") for item in events)

    other = auth("materials-qa-stranger")
    assert client.get(f"/api/lectures/{LECTURE}/pages", params={"file_id": file_id}, headers=other).status_code == 404
    assert client.post("/api/chat/stream", headers=other,
                       json={"message": "Read this lecture.", "lecture_id": LECTURE}).status_code == 404
    other_choices = client.get("/api/qa/lectures", headers=other).json()["data"]["items"]
    assert all(item["id"] != LECTURE for item in other_choices)
    assert len(seen) == 1, "An unauthorized lecture must never reach the QA model"


def test_uploaded_material_reaches_practice_handoff_without_claiming_real_quiz_generation(client, auth, monkeypatch):
    headers = auth("materials-practice-handoff")
    monkeypatch.setattr(materials_service, "has_llm", lambda **_: False)
    _, status = upload(client, headers, pdf_bytes(PAGE_ONE), lecture=LECTURE)
    assert status["parse_status"] == "parsed"
    monkeypatch.setattr(qa_service, "classify", lambda *_: {"intent": "quiz", "mock": False})
    events = frames(client.post("/api/chat/stream", headers=headers,
                               json={"message": "出 2 道题", "lecture_id": LECTURE}))
    handoff = next(item for item in events if item.get("type") == "handoff")
    assert handoff["intent"] == "quiz" and handoff["data"]["lecture_id"] == LECTURE
    # Main's practice implementation is still a sample; keep that provenance.
    assert handoff["data"]["mock"] is True
    assert next(item for item in events if item.get("type") == "complete")["mock"] is True


def stored_page(user, lecture, number, text, file_id=""):
    ensure_schema()
    with user_scope(user), SessionLocal() as session:
        session.add(MaterialPage(id=uuid.uuid4().hex, user_id=user, lecture_id=lecture,
                                 page_no=number, text=text, file_id=file_id))
        session.commit()


def test_main_existing_page_import_remains_real_and_user_scoped(uid):
    stored_page(uid, "imported-before-upload", 3, PAGE_THREE)
    stored_page("other-owner", "imported-before-upload", 1, "Another owner's source.")
    pages = fetch_lecture_pages(uid, "imported-before-upload")
    assert pages == [{"lecture_id": "imported-before-upload", "page": 3, "text": PAGE_THREE, "mock": False}]
    assert fetch_lecture_pages(uid, "other-unknown-lecture") == []


def test_legacy_fallback_selects_one_file_group_instead_of_joining_versions(uid):
    stored_page(uid, "legacy-versions", 1, "One first version.", file_id="legacy-file-a")
    stored_page(uid, "legacy-versions", 1, "A replacement source.", file_id="legacy-file-b")
    stored_page(uid, "legacy-versions", 2, "Its second page.", file_id="legacy-file-b")
    pages = fetch_lecture_pages(uid, "legacy-versions")
    assert len({page["file_id"] for page in pages}) == 1
    assert len({page["page"] for page in pages}) == len(pages)


def test_foundation_sample_stays_explicitly_mock_when_persisted(uid):
    for item in SAMPLE_PAGES:
        stored_page(uid, "lec-6", item["page"], item["text"])
    pages = fetch_lecture_pages(uid, "lec-6")
    assert all(page["mock"] is True and page["sample"] is True for page in pages)


def test_managed_upload_wins_over_legacy_records_and_preserves_requested_version(client, auth, monkeypatch):
    owner = "materials-legacy-replaced"
    headers = auth(owner)
    stored_page(owner, LECTURE, 1, "Old unversioned imported material.")
    monkeypatch.setattr(materials_service, "has_llm", lambda **_: False)
    first_id, _ = upload(client, headers, pdf_bytes(PAGE_ONE), lecture=LECTURE)
    second_id, _ = upload(client, headers, pdf_bytes(PAGE_THREE), lecture=LECTURE)
    current = client.get(f"/api/lectures/{LECTURE}/pages", headers=headers).json()["data"]["pages"]
    first = client.get(f"/api/lectures/{LECTURE}/pages", params={"file_id": first_id}, headers=headers).json()["data"]["pages"]
    assert len(current) == len(first) == 1
    assert current[0]["file_id"] == second_id and PAGE_THREE in current[0]["text"]
    assert first[0]["file_id"] == first_id and PAGE_ONE in first[0]["text"]
    assert all("Old unversioned" not in page["text"] for page in current + first)
