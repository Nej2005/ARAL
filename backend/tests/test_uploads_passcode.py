"""Chunked uploads and the passcode guard."""

from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from tests.conftest import API, process_document


def _chunked_upload(client, path, chunk_mb=None, corrupt=False, reviewer_id=None):
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    start = client.post(f"{API}/uploads", json={"filename": path.name, "size": len(data), "sha256": sha, "reviewer_id": reviewer_id})
    assert start.status_code == 200, start.text
    s = start.json()
    if s["duplicate"]:
        return s
    size = s["chunk_size"]
    assert s["chunk_count"] == -(-len(data) // size)
    for i in range(s["chunk_count"]):
        part = data[i * size:(i + 1) * size]
        if corrupt and i == 0:
            part = b"X" + part[1:]
        r = client.put(f"{API}/uploads/{s['upload_id']}/chunks/{i}", content=part)
        assert r.status_code == 200, r.text
    done = client.post(f"{API}/uploads/{s['upload_id']}/complete", json={"reviewer_id": reviewer_id})
    return {"_status_code": done.status_code, **done.json()}


def test_chunked_upload_in_small_chunks(client, fixture_files, monkeypatch, fake_llm):
    monkeypatch.setattr(settings, "upload_chunk_mb", 0)  # forces 0-byte chunk size? no: use bytes override below
    monkeypatch.setattr(type(settings), "upload_chunk_bytes", property(lambda self: 8000))
    d = _chunked_upload(client, fixture_files["pdf"])
    assert d["_status_code"] == 202 and d["duplicate"] is False and d["status"] == "uploaded"
    assert d["size"] == fixture_files["pdf"].stat().st_size
    assert process_document(client, d["id"])["status"] == "ready"

    # duplicate recognized at start -> no chunks sent
    again = _chunked_upload(client, fixture_files["pdf"])
    assert again["duplicate"] is True and again["document"]["id"] == d["id"]


def test_chunked_upload_detects_corruption_and_missing_chunks(client, fixture_files, monkeypatch):
    monkeypatch.setattr(type(settings), "upload_chunk_bytes", property(lambda self: 8000))
    bad = _chunked_upload(client, fixture_files["pptx"], corrupt=True)
    assert bad["_status_code"] == 400 and bad["error"]["code"] == "UPLOAD_CORRUPT"

    data = fixture_files["pptx"].read_bytes()
    start = client.post(f"{API}/uploads", json={"filename": "x.pptx", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}).json()
    client.put(f"{API}/uploads/{start['upload_id']}/chunks/0", content=data[:8000])
    inc = client.post(f"{API}/uploads/{start['upload_id']}/complete")
    assert inc.status_code == 409 and inc.json()["error"]["code"] == "UPLOAD_INCOMPLETE"
    wrong = client.put(f"{API}/uploads/{start['upload_id']}/chunks/1", content=b"short")
    assert wrong.status_code == 400 and wrong.json()["error"]["code"] == "BAD_CHUNK"
    assert client.post(f"{API}/uploads", json={"filename": "x.docx", "size": 10, "sha256": "a" * 64}).json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    assert client.post(f"{API}/uploads", json={"filename": "x.pdf", "size": 10 ** 9, "sha256": "a" * 64}).json()["error"]["code"] == "FILE_TOO_LARGE"


def test_passcode_guard(test_db, fake_llm, monkeypatch):
    monkeypatch.setattr(settings, "app_passcode", "secret-123")
    app.state.skip_migrations = True
    with TestClient(app) as c:
        assert c.get(f"{API}/health").json()["passcode_required"] is True
        r = c.get(f"{API}/reviewers")
        assert r.status_code == 401 and r.json()["error"]["code"] == "PASSCODE_REQUIRED"
        r = c.get(f"{API}/reviewers", headers={"X-Passcode": "nope"})
        assert r.status_code == 401 and r.json()["error"]["code"] == "PASSCODE_WRONG"
        assert c.get(f"{API}/reviewers", headers={"X-Passcode": "secret-123"}).status_code == 200
        assert c.get(f"{API}/reviewers?passcode=secret-123").status_code == 200  # for download links
