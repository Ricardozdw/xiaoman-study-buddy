import io

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def pdf_bytes(text="Learning from data."):
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 30 250 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = io.BytesIO(); writer.write(buffer)
    return buffer.getvalue()


def test_upload_real_pdf_extracts_and_can_quiz(client, auth):
    headers = auth("upload-a")
    response = client.post("/api/practice/materials", files={"file": ("my-lecture.pdf", pdf_bytes(), "application/pdf")}, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mock"] is False
    data = body["data"]
    assert data["filename"] == "my-lecture.pdf" and data["page_count"] == 1 and not data["reused"]
    pages = client.get(f"/api/lectures/{data['lecture_id']}/pages", headers=headers).json()["data"]["pages"]
    assert "Learning from data." in pages[0]["text"]
    quiz = client.post("/api/quizzes", json={"lecture_id": data["lecture_id"], "count": 1}, headers=headers)
    assert quiz.status_code == 200
    assert "Learning from data." in str(quiz.json()["data"]["questions"][0]["options"])
    assert client.get("/api/practice/materials", headers=auth("upload-b")).json()["data"]["items"] == []
    repeated = client.post("/api/practice/materials", files={"file": ("my-lecture.pdf", pdf_bytes(), "application/pdf")}, headers=headers)
    assert repeated.json()["data"]["reused"]
    assert len(client.get("/api/practice/materials", headers=headers).json()["data"]["items"]) == 1


def test_upload_rejects_wrong_type_fake_pdf_and_scan(client, auth):
    headers = auth("upload-invalid")
    for name, data in [("file.txt", b"hello"), ("fake.pdf", b"not a PDF")]:
        r = client.post("/api/practice/materials", files={"file": (name, data)}, headers=headers)
        assert r.status_code == 422
    writer = PdfWriter(); writer.add_blank_page(300, 300)
    buffer = io.BytesIO(); writer.write(buffer)
    r = client.post("/api/practice/materials", files={"file": ("scan.pdf", buffer.getvalue())}, headers=headers)
    assert r.status_code == 422 and "文字" in r.json()["detail"]["message"]


def test_upload_limit_and_filename_safety(client, auth, monkeypatch):
    headers = auth("upload-limits")
    monkeypatch.setattr("app.study.practice.uploads.MAX_FILE_BYTES", 8)
    r = client.post("/api/practice/materials", files={"file": ("large.pdf", b"%PDF-" + b"x" * 20)}, headers=headers)
    assert r.status_code == 413
    monkeypatch.setattr("app.study.practice.uploads.MAX_FILE_BYTES", 20 * 1024 * 1024)
    r = client.post("/api/practice/materials", files={"file": ("../../safe.pdf", pdf_bytes())}, headers=headers)
    assert r.status_code == 200 and r.json()["data"]["filename"] == "safe.pdf"


def test_model_status_does_not_expose_secrets(client, auth):
    data = client.get("/api/practice/status", headers=auth("status-a")).json()["data"]
    assert data["configured"] is False and "model_chain" in data
    assert "api_key" not in str(data).lower()
