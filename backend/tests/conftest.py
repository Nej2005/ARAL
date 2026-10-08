from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import db as dbmod
from app.config import settings
from app.main import app, run_migrations
from app.services import llm
from tests.fake_llm import FakeLLM
from tests.fixtures import build_pdf, build_pptx

API = "/api/v1"


@pytest.fixture(scope="session")
def fixture_files(tmp_path_factory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("fixtures")
    return {"pptx": build_pptx(d / "sample.pptx"), "pdf": build_pdf(d / "sample.pdf")}


@pytest.fixture()
def fake_llm():
    fake = FakeLLM()
    llm.set_backend(fake)
    yield fake
    llm.set_backend(None)


@pytest.fixture()
def test_db(tmp_path, monkeypatch):
    import os

    url = os.environ.get("TEST_DATABASE_URL") or "sqlite:///" + str(tmp_path / "test.db").replace("\\", "/")
    eng = dbmod.make_engine(url)
    if not url.startswith("sqlite"):
        from sqlalchemy import text

        from app.db import Base

        Base.metadata.drop_all(eng)
        with eng.begin() as conn:  # so the migrations run again from scratch
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    dbmod.set_engine(eng)
    run_migrations(url)  # the real migrations, so they are exercised too
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    monkeypatch.setattr(settings, "llm_min_seconds_between_calls", 0)
    monkeypatch.setattr(settings, "app_passcode", "")
    yield eng
    eng.dispose()


@pytest.fixture()
def session(test_db) -> Session:
    s = dbmod.SessionLocal()
    yield s
    s.close()


@pytest.fixture()
def client(test_db, fake_llm):
    app.state.skip_migrations = True
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------- helpers used by the API tests


def process_document(client: TestClient, doc_id: str, max_steps: int = 50) -> dict:
    """Drive /process until the document is ready or failed (what the frontend does)."""
    for _ in range(max_steps):
        r = client.post(f"{API}/documents/{doc_id}/process")
        assert r.status_code == 200, r.text
        d = r.json()
        if d["done"]:
            return d
    raise AssertionError("document did not finish processing")


def upload(client: TestClient, path: Path, reviewer_id: str | None = None, process: bool = True) -> dict:
    """Upload through the single-request route and (by default) process it to the end."""
    with open(path, "rb") as f:
        data = {"reviewer_id": reviewer_id} if reviewer_id else {}
        r = client.post(f"{API}/documents", files={"file": (path.name, f, "application/octet-stream")}, data=data)
    out = r.json()
    out["_status_code"] = r.status_code
    if r.status_code in (200, 202) and process and out.get("status") in ("uploaded", "extracting"):
        out = {**process_document(client, out["id"]), "duplicate": out.get("duplicate"), "_status_code": r.status_code}
    return out


def make_exam(client: TestClient, reviewer_id: str, body: dict) -> dict:
    """Create an exam and run its processing step. Returns the exam (ready or failed), or the error."""
    r = client.post(f"{API}/reviewers/{reviewer_id}/exams", json=body)
    if r.status_code != 202:
        return {"_status_code": r.status_code, **r.json()}
    p = client.post(f"{API}/exams/{r.json()['id']}/process")
    assert p.status_code == 200, p.text
    return {"_status_code": 202, **p.json()}


def next_set(client: TestClient, exam_id: str, body: dict | None = None) -> dict:
    r = client.post(f"{API}/exams/{exam_id}/next-set", json=body) if body is not None else client.post(f"{API}/exams/{exam_id}/next-set")
    if r.status_code != 202:
        return {"_status_code": r.status_code, **r.json()}
    p = client.post(f"{API}/exams/{r.json()['id']}/process")
    return {"_status_code": 202, **p.json()}
