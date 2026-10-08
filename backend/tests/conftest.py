from __future__ import annotations

import os
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
    url = "sqlite:///" + str(tmp_path / "test.db").replace("\\", "/")
    eng = dbmod.make_engine(url)
    dbmod.set_engine(eng)
    run_migrations(url)  # the real migrations, so they are exercised too
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    monkeypatch.setattr(settings, "llm_min_seconds_between_calls", 0)
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
    with TestClient(app) as c:  # background tasks run before the response is returned
        yield c


def upload(client: TestClient, path: Path, reviewer_id: str | None = None):
    with open(path, "rb") as f:
        data = {"reviewer_id": reviewer_id} if reviewer_id else {}
        return client.post("/api/v1/documents", files={"file": (path.name, f, "application/octet-stream")}, data=data)
