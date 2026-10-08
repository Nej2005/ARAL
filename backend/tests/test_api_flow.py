"""The whole flow through the HTTP API with the fake Gemini (BACKEND.md §15 "API")."""

from __future__ import annotations

import csv
import io

from app.services import llm
from tests.conftest import API, make_exam, next_set, process_document, upload
from tests.fixtures import build_pdf, build_pptx


def _ready_reviewer(client, fixture_files, title="Biology Midterm"):
    d1 = upload(client, fixture_files["pptx"])
    d2 = upload(client, fixture_files["pdf"])
    assert d1["status"] == "ready" and d2["status"] == "ready", (d1, d2)
    r = client.post(f"{API}/reviewers", json={"title": title, "document_ids": [d1["id"], d2["id"]]}).json()
    return r, d1, d2


def _wrong_answer(q):
    if q["type"] == "mcq":
        return q["choices"][0]["id"]  # may or may not be right; shuffled
    if q["type"] == "true_false":
        return "true"
    return "zzz-not-a-term"


# --------------------------------------------------------------------------- documents


def test_upload_extract_and_duplicates(client, fixture_files, fake_llm, tmp_path):
    first = upload(client, fixture_files["pptx"], process=False)
    assert first["_status_code"] == 202 and first["duplicate"] is False and first["status"] == "uploaded"
    # step 1 reads the pages, step 2 is the single Gemini window (5 slides fit in one)
    s1 = client.post(f"{API}/documents/{first['id']}/process").json()
    assert s1["status"] == "extracting" and s1["page_count"] == 5 and s1["steps_done"] == 1 and s1["steps_total"] == 2
    assert len(fake_llm.calls) == 0
    s2 = client.post(f"{API}/documents/{first['id']}/process").json()
    assert s2["status"] == "ready" and s2["done"] is True and s2["item_count"] >= 10
    assert s2["items_by_kind"]["definition"] >= 8 and s2["outdated"] is False
    assert len(fake_llm.calls) == 1
    # processing a ready document is a no-op
    assert client.post(f"{API}/documents/{first['id']}/process").json()["status"] == "ready"
    assert len(fake_llm.calls) == 1

    # Same bytes again -> 200, duplicate, no Gemini call
    again = upload(client, fixture_files["pptx"])
    assert again["_status_code"] == 200 and again["duplicate"] is True and again["id"] == first["id"]
    assert len(fake_llm.calls) == 1

    # Same text in a different file (new bytes) -> items copied, no Gemini call
    other = build_pptx(tmp_path / "again.pptx", variant="saved again")
    d3 = upload(client, other)
    assert d3["duplicate"] is False and d3["status"] == "ready" and d3["copied_from_document_id"] == first["id"]
    assert d3["item_count"] == s2["item_count"]
    assert len(fake_llm.calls) == 1
    assert len(client.get(f"{API}/documents").json()) == 2


def test_file_bytes_are_dropped_after_pages_are_read(client, fixture_files, session):
    from app.models import DocumentFile

    d = upload(client, fixture_files["pdf"], process=False)
    assert session.get(DocumentFile, d["id"]) is not None
    client.post(f"{API}/documents/{d['id']}/process")
    session.expire_all()
    assert session.get(DocumentFile, d["id"]) is None


def test_upload_rejects_bad_files(client, tmp_path):
    bad = tmp_path / "notes.docx"
    bad.write_text("hello")
    assert upload(client, bad)["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_bytes(b"not really a pdf")
    assert upload(client, fake_pdf)["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


def test_scanned_pdf_fails_cleanly_and_duplicate_failed_is_retried(client, tmp_path, fake_llm):
    from tests.fixtures import build_empty_pdf

    p = build_empty_pdf(tmp_path / "scan.pdf")
    d = upload(client, p)
    assert d["status"] == "failed" and d["error_code"] == "NO_EXTRACTABLE_TEXT"
    r2 = upload(client, p, process=False)
    assert r2["_status_code"] == 202 and r2["duplicate"] is True and r2["status"] == "uploaded"  # re-run offered


def test_quota_stop_resumes_where_it_left_off(client, tmp_path, fake_llm, monkeypatch):
    from app.config import settings
    from tests.fixtures import RESP_PAGES

    monkeypatch.setattr(settings, "extraction_window_pages", 2)  # 4 pages -> 3 windows (1-page overlap)
    pdf = build_pdf(tmp_path / "long.pdf")
    calls = {"n": 0}
    real = fake_llm.__call__

    def flaky(system, user, schema, label=""):
        calls["n"] += 1
        if calls["n"] == 2:
            raise llm.LLMQuotaExceeded("daily limit")
        return real(system, user, schema, label)

    llm.set_backend(flaky)
    d = upload(client, pdf)
    assert d["status"] == "failed" and d["error_code"] == "LLM_QUOTA_EXCEEDED"
    assert d["extraction_progress"] == 1 and d["item_count"] > 0  # first window was saved
    assert d["steps_done"] == 2 and d["steps_total"] == 4

    rr = client.post(f"{API}/documents/{d['id']}/reprocess")
    assert rr.status_code == 202 and rr.json()["resumed"] is True
    d2 = process_document(client, d["id"])
    assert d2["status"] == "ready"
    assert calls["n"] == 4  # 1 ok + 1 fail + 2 remaining windows (never redid window 1)
    assert d2["item_count"] >= len([l for _, ls in RESP_PAGES for l in ls]) - 2


def test_reprocess_supersedes_items_and_old_exams_still_render(client, fixture_files, fake_llm):
    r, d1, d2 = _ready_reviewer(client, fixture_files)
    e = make_exam(client, r["id"], {"types": ["identification"], "count": 3})
    assert e["status"] == "ready"
    before = client.get(f"{API}/reviewers/{r['id']}").json()
    assert before["used_items"] == 3
    rr = client.post(f"{API}/documents/{d1['id']}/reprocess")
    assert rr.status_code == 202 and rr.json()["resumed"] is False
    assert process_document(client, d1["id"])["status"] == "ready"
    after = client.get(f"{API}/reviewers/{r['id']}").json()
    assert after["item_count"] == before["item_count"]
    assert after["used_items"] <= before["used_items"]  # new ids -> not counted as used
    a = client.post(f"{API}/exams/{e['id']}/attempts").json()
    assert a["card"]["question"]["prompt"]


def test_stale_claims_are_cleared_and_busy_documents_are_skipped(client, fixture_files, session, fake_llm):
    from app import jobs
    from app.models import Document, utcnow

    d = upload(client, fixture_files["pdf"], process=False)
    doc = session.get(Document, d["id"])
    doc.step_started_at = utcnow()  # another request is "working" on it
    session.commit()
    busy = client.post(f"{API}/documents/{d['id']}/process").json()
    assert busy["busy"] is True and busy["status"] == "uploaded" and busy["page_count"] == 0  # no work done
    assert jobs.clear_stale_claims() == 1
    assert process_document(client, d["id"])["status"] == "ready"


# --------------------------------------------------------------------------- reviewers


def test_reviewer_crud_outline_and_document_rules(client, fixture_files):
    r, d1, d2 = _ready_reviewer(client, fixture_files)
    assert r["document_count"] == 2 and r["status"] == "ready" and r["used_items"] == 0
    lst = client.get(f"{API}/reviewers").json()
    assert lst[0]["id"] == r["id"] and lst[0]["last_score"] is None

    o = client.get(f"{API}/reviewers/{r['id']}/outline").json()
    assert [d["document_id"] for d in o["documents"]] == [d1["id"], d2["id"]]
    assert o["documents"][0]["pages"][0]["item_count"] >= 2
    topics = {t["topic_key"] for t in o["topics"]}
    assert "photosynthesis" in topics  # "Photosynthesis" + "Photosynthesis (cont.)" grouped
    assert sum(1 for t in o["topics"] if t["topic_key"] == "photosynthesis") == 1

    p = client.patch(f"{API}/reviewers/{r['id']}", json={"title": "Midterm", "document_order": [d2["id"], d1["id"]]}).json()
    assert p["title"] == "Midterm" and [d["id"] for d in p["documents"]] == [d2["id"], d1["id"]]
    assert client.patch(f"{API}/reviewers/{r['id']}", json={"document_order": [d1["id"]]}).status_code == 422

    assert client.delete(f"{API}/reviewers/{r['id']}/documents/{d1['id']}").json()["document_count"] == 1
    assert client.delete(f"{API}/reviewers/{r['id']}/documents/{d2['id']}").json()["error"]["code"] == "EMPTY_REVIEWER"
    assert client.post(f"{API}/reviewers/{r['id']}/documents", json={"document_id": d1["id"]}).json()["document_count"] == 2

    assert client.delete(f"{API}/documents/{d1['id']}").json()["error"]["code"] == "DOCUMENT_IN_USE"
    assert client.delete(f"{API}/documents/{d1['id']}?force=true").status_code == 204
    assert client.get(f"{API}/reviewers/{r['id']}").json()["document_count"] == 1
    assert client.delete(f"{API}/reviewers/{r['id']}").status_code == 204
    assert client.get(f"{API}/reviewers/{r['id']}").status_code == 404
    assert client.get(f"{API}/documents/{d2['id']}").status_code == 200  # library keeps the file


def test_exam_needs_ready_documents(client, fixture_files, fake_llm):
    fake_llm.fail_with = llm.LLMError("boom")
    d = upload(client, fixture_files["pdf"])
    assert d["status"] == "failed"
    r = client.post(f"{API}/reviewers", json={"title": "X", "document_ids": [d["id"]]}).json()
    assert r["status"] == "needs_attention"
    e = make_exam(client, r["id"], {"types": ["mcq"], "count": 5})
    assert e["_status_code"] == 409 and e["error"]["code"] == "DOCUMENTS_NOT_READY"


# --------------------------------------------------------------------------- exams + flashcards


def test_full_exam_flow(client, fixture_files, fake_llm):
    r, d1, d2 = _ready_reviewer(client, fixture_files)
    av = client.post(f"{API}/reviewers/{r['id']}/availability", json={"types": ["mcq", "true_false", "identification"]}).json()
    assert av["unused_items"] == av["total_items"] >= 20 and av["unused_outside_scope"] == 0

    created = client.post(f"{API}/reviewers/{r['id']}/exams", json={"types": ["mcq", "true_false", "identification"], "count": 9})
    assert created.status_code == 202 and created.json()["status"] == "generating"
    assert client.get(f"{API}/reviewers/{r['id']}").json()["used_items"] == 0  # not until it's ready
    exam = client.post(f"{API}/exams/{created.json()['id']}/process").json()
    assert exam["status"] == "ready", exam
    assert exam["actual_count"] == 9 and exam["shortfall"] == 0 and exam["done"] is True
    assert sum(1 for c in fake_llm.calls if c[0] == "GenerationBatch") == 1  # one batched call
    assert client.post(f"{API}/exams/{exam['id']}/process").json()["status"] == "ready"  # no-op
    assert sum(1 for c in fake_llm.calls if c[0] == "GenerationBatch") == 1
    assert client.get(f"{API}/reviewers/{r['id']}").json()["used_items"] == 9

    a = client.post(f"{API}/exams/{exam['id']}/attempts")
    assert a.status_code == 201
    att = a.json()
    aid = att["attempt_id"]
    card1 = att["card"]
    assert card1["index"] == 1 and card1["answered"] is False
    assert "feedback" not in card1 and "correct_answer" not in card1
    if card1["question"]["type"] == "mcq":
        assert len(card1["question"]["choices"]) == 4
        assert all("source_item_id" not in c for c in card1["question"]["choices"])

    m = client.get(f"{API}/attempts/{aid}").json()
    assert m["total"] == 9 and all(c["status"] == "unanswered" for c in m["cards"])
    types = {}
    for c in m["cards"]:
        q = client.get(f"{API}/attempts/{aid}/cards/{c['index']}").json()["question"]
        types[q["type"]] = types.get(q["type"], 0) + 1
    assert types == {"mcq": 3, "true_false": 3, "identification": 3}

    c2 = client.get(f"{API}/attempts/{aid}/cards/2").json()
    assert client.get(f"{API}/attempts/{aid}").json()["last_viewed_index"] == 2
    q2 = c2["question"]
    resp = client.post(f"{API}/attempts/{aid}/answer", json={"question_id": q2["id"], "response": _wrong_answer(q2)})
    assert resp.status_code == 200
    fb = resp.json()
    assert fb["finished"] is False and fb["progress"]["answered"] == 1 and fb["next_unanswered_index"] == 3
    f = fb["feedback"]
    assert f["why"] and f["source"]["quote"] and f["source"]["filename"] and f["source"]["location"]
    assert f["correct_answer"]["text"]
    if q2["type"] == "mcq" and not f["is_correct"]:
        assert f["why_yours_is_wrong"]
    if q2["type"] == "true_false" and f["correct_answer"]["text"] == "false":
        assert f["changed_span"]["from"] != f["changed_span"]["to"]
        assert f["changed_span"]["to"] in q2["prompt"]

    again = client.post(f"{API}/attempts/{aid}/answer", json={"question_id": q2["id"], "response": "x"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "ALREADY_ANSWERED"
    back = client.get(f"{API}/attempts/{aid}/cards/2").json()
    assert back["answered"] is True and back["feedback"] == f

    last = None
    for i in range(3, 10):
        q = client.get(f"{API}/attempts/{aid}/cards/{i}").json()["question"]
        last = client.post(f"{API}/attempts/{aid}/answer", json={"question_id": q["id"], "response": _wrong_answer(q)}).json()
    assert last["finished"] is False and last["next_unanswered_index"] == 1
    assert client.get(f"{API}/attempts/{aid}/summary").json()["error"]["code"] == "ATTEMPT_NOT_FINISHED"
    assert client.get(f"{API}/attempts/{aid}/cards/99").status_code == 404

    s = client.post(f"{API}/attempts/{aid}/finish").json()
    assert s["total"] == 9 and s["answered"] == 8 and s["skipped"] == 1
    assert s["correct_count"] + len(s["wrong_cards"]) + len(s["skipped_cards"]) == 9
    assert s["retry_mistakes"]["count"] == len(s["wrong_cards"]) + 1
    assert s["next_set"]["unused_items"] == av["total_items"] - 9
    skipped = s["skipped_cards"][0]
    assert skipped["your_answer"] is None and skipped["correct_answer"]["text"]
    assert client.post(f"{API}/attempts/{aid}/answer", json={"question_id": q2["id"], "response": "x"}).json()["error"]["code"] == "ATTEMPT_COMPLETED"

    n_calls = len(fake_llm.calls)
    rm = client.post(f"{API}/attempts/{aid}/retry-mistakes")
    assert rm.status_code == 201 and rm.json()["kind"] == "mistakes"
    assert rm.json()["total"] == s["retry_mistakes"]["count"]
    assert len(fake_llm.calls) == n_calls
    assert client.get(f"{API}/reviewers/{r['id']}").json()["used_items"] == 9
    rid = rm.json()["attempt_id"]
    assert client.post(f"{API}/attempts/{rid}/retry-mistakes").json()["error"]["code"] == "ATTEMPT_NOT_FINISHED"

    rs = client.post(f"{API}/exams/{exam['id']}/attempts").json()
    assert rs["attempt_no"] == 3 and rs["total"] == 9
    lst = client.get(f"{API}/reviewers/{r['id']}/exams").json()
    assert lst[0]["id"] == exam["id"] and lst[0]["attempt_count"] == 3 and lst[0]["best_score"]["total"] == 9
    assert lst[0]["latest_attempt_id"] == aid and lst[0]["in_progress_attempt_id"] == rs["attempt_id"]
    assert client.get(f"{API}/reviewers").json()[0]["last_score"] == {"correct_count": s["correct_count"], "total": 9}


def test_answers_graded_correctly_with_known_answers(client, fixture_files, session):
    from app.models import Question

    r, *_ = _ready_reviewer(client, fixture_files)
    e = make_exam(client, r["id"], {"types": ["mcq", "true_false", "identification"], "count": 6})
    att = client.post(f"{API}/exams/{e['id']}/attempts").json()
    aid = att["attempt_id"]
    for i in range(1, 7):
        card = client.get(f"{API}/attempts/{aid}/cards/{i}").json()
        q = session.get(Question, card["question"]["id"])
        resp = q.correct_answer if q.type != "identification" else q.correct_answer.upper() + "  "
        out = client.post(f"{API}/attempts/{aid}/answer", json={"question_id": q.id, "response": resp}).json()
        assert out["feedback"]["is_correct"] is True, (q.type, q.prompt, resp, out)
        assert out["feedback"]["why_yours_is_wrong"] is None
    assert out["finished"] is True
    s = client.get(f"{API}/attempts/{aid}/summary").json()
    assert s["correct_count"] == 6 and s["percent"] == 100 and s["wrong_cards"] == []
    assert client.post(f"{API}/attempts/{aid}/retry-mistakes").json()["error"]["code"] == "NO_MISTAKES"


def test_identification_feedback_names_other_term_and_typo(client, fixture_files, session):
    from app.models import Question, SourceItem

    r, *_ = _ready_reviewer(client, fixture_files)
    e = make_exam(client, r["id"], {"types": ["identification"], "count": 6})
    aid = client.post(f"{API}/exams/{e['id']}/attempts").json()["attempt_id"]
    card = client.get(f"{API}/attempts/{aid}/cards/1").json()
    q = session.get(Question, card["question"]["id"])
    other = session.query(SourceItem).filter(SourceItem.id != q.source_item_id, SourceItem.term.isnot(None)).first()
    out = client.post(f"{API}/attempts/{aid}/answer", json={"question_id": q.id, "response": other.term}).json()
    assert out["feedback"]["is_correct"] is False
    assert out["feedback"]["why_yours_is_wrong"].startswith(f"'{other.term}' is a different concept")

    tested_typo = False
    for i in range(2, 7):
        card = client.get(f"{API}/attempts/{aid}/cards/{i}").json()
        q = session.get(Question, card["question"]["id"])
        term = q.correct_answer
        if len(term) >= 10 and not tested_typo:
            typo = term[:-1] + ("x" if term[-1] != "x" else "y")
            out = client.post(f"{API}/attempts/{aid}/answer", json={"question_id": q.id, "response": typo}).json()
            assert out["feedback"]["is_correct"] is True and out["feedback"]["match_note"] == "typo_tolerated", (term, typo, out)
            tested_typo = True
        else:
            client.post(f"{API}/attempts/{aid}/answer", json={"question_id": q.id, "response": term})
    assert tested_typo


def test_scope_next_set_coverage_reset(client, fixture_files, fake_llm):
    r, d1, d2 = _ready_reviewer(client, fixture_files)
    o = client.get(f"{API}/reviewers/{r['id']}/outline").json()
    pptx_items = sum(p["item_count"] for p in o["documents"][0]["pages"])

    bad = make_exam(client, r["id"], {"types": ["mcq"], "count": 3, "scope": {"documents": [{"document_id": d1["id"], "pages": [[1, 99]]}]}})
    assert bad["_status_code"] == 422 and bad["error"]["code"] == "INVALID_SCOPE"

    scope = {"documents": [{"document_id": d1["id"]}]}
    av = client.post(f"{API}/reviewers/{r['id']}/availability", json={"types": ["mcq"], "scope": scope}).json()
    assert av["unused_items"] == pptx_items and av["unused_outside_scope"] == av["total_items"] - pptx_items

    e1 = make_exam(client, r["id"], {"types": ["mcq"], "count": pptx_items, "scope": scope})
    assert e1["status"] == "ready" and e1["actual_count"] == pptx_items and e1["scope"] == scope

    ns = next_set(client, e1["id"])
    assert ns["_status_code"] == 409 and ns["error"]["code"] == "ALL_ITEMS_REVIEWED"
    assert ns["error"]["unused_outside_scope"] == av["total_items"] - pptx_items

    e2 = next_set(client, e1["id"], {"scope": None, "count": 99})
    assert e2["_status_code"] == 202 and e2["parent_exam_id"] == e1["id"]
    assert e2["status"] == "ready" and e2["scope"] is None
    assert e2["actual_count"] == av["total_items"] - pptx_items and e2["shortfall"] == 99 - e2["actual_count"]

    assert make_exam(client, r["id"], {"types": ["mcq"], "count": 1})["error"]["code"] == "ALL_ITEMS_REVIEWED"
    assert client.post(f"{API}/reviewers/{r['id']}/coverage/reset").json()["coverage_epoch"] == 1
    assert client.get(f"{API}/reviewers/{r['id']}").json()["unused_items"] == av["total_items"]
    assert make_exam(client, r["id"], {"types": ["mcq"], "count": 1})["status"] == "ready"
    assert client.get(f"{API}/exams/{e1['id']}").json()["actual_count"] == pptx_items


def test_adding_a_document_later_adds_unused_items(client, fixture_files):
    d1 = upload(client, fixture_files["pptx"])
    r = client.post(f"{API}/reviewers", json={"title": "One file", "document_ids": [d1["id"]]}).json()
    e = make_exam(client, r["id"], {"types": ["true_false"], "count": 100})
    assert e["actual_count"] == r["item_count"]
    assert client.get(f"{API}/reviewers/{r['id']}").json()["unused_items"] == 0
    d2 = upload(client, fixture_files["pdf"], reviewer_id=r["id"])
    rr = client.get(f"{API}/reviewers/{r['id']}").json()
    assert rr["document_count"] == 2 and rr["unused_items"] > 0
    assert d2["id"] in [d["id"] for d in rr["documents"]]


def test_generation_failure_is_reported_on_the_exam(client, fixture_files, fake_llm):
    r, *_ = _ready_reviewer(client, fixture_files)
    fake_llm.fail_with = llm.LLMQuotaExceeded("limit")
    ex = make_exam(client, r["id"], {"types": ["mcq"], "count": 3})
    assert ex["status"] == "failed" and ex["error_code"] == "LLM_QUOTA_EXCEEDED"
    assert client.post(f"{API}/exams/{ex['id']}/attempts").json()["error"]["code"] == "EXAM_NOT_READY"
    assert client.get(f"{API}/reviewers/{r['id']}").json()["used_items"] == 0  # failed exams don't use items


def test_bad_rationale_falls_back_to_template(client, fixture_files, fake_llm, session):
    from app.models import Question

    fake_llm.bad_rationale_for = {"q1", "q2", "q3"}
    r, *_ = _ready_reviewer(client, fixture_files)
    e = make_exam(client, r["id"], {"types": ["identification"], "count": 3})
    qs = session.query(Question).filter(Question.exam_id == e["id"]).all()
    assert len(qs) == 3 and all(q.rationale.startswith("The lesson states: '") for q in qs)


# --------------------------------------------------------------------------- export


def test_exports(client, fixture_files):
    r, d1, d2 = _ready_reviewer(client, fixture_files)
    e = make_exam(client, r["id"], {"types": ["mcq", "true_false", "identification"], "count": 6})

    pdf = client.get(f"{API}/exams/{e['id']}/export?format=pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and len(pdf.content) > 5000
    assert 'filename="biology-midterm-exam-1.pdf"' in pdf.headers["content-disposition"]
    pdf2 = client.get(f"{API}/exams/{e['id']}/export?format=pdf&answer_key=none")
    assert len(pdf2.content) < len(pdf.content)

    csv_r = client.get(f"{API}/exams/{e['id']}/export?format=csv")
    assert csv_r.status_code == 200
    text = csv_r.content.decode("utf-8")
    head, body = text.split("#tags column:3\n", 1)
    assert head.startswith("#separator:comma\n#html:true\n#notetype:Basic\n#deck:ARAL::Biology Midterm\n#columns:Front,Back,Tags\n")
    rows = list(csv.reader(io.StringIO(body)))
    assert len(rows) == 6 and all(len(r) == 3 for r in rows)
    assert all("aral" in r[2] and "reviewer::biology-midterm" in r[2] for r in rows)
    assert any("type::mcq" in r[2] and "<br>A. " in r[0] for r in rows)
    assert "<script>" not in text

    sheet = client.post(f"{API}/reviewers/{r['id']}/export", json={"format": "pdf"})
    assert sheet.status_code == 200 and sheet.content.startswith(b"%PDF")
    items_csv = client.post(f"{API}/reviewers/{r['id']}/export", json={"format": "csv",
                                                                       "scope": {"documents": [{"document_id": d2["id"]}]}})
    body2 = items_csv.content.decode("utf-8").split("#tags column:3\n", 1)[1]
    rows2 = list(csv.reader(io.StringIO(body2)))
    assert rows2 and all("file::sample-pdf" in r[2] for r in rows2)
    assert any(r[0] == "ATP" and r[1].startswith("the main energy-carrying molecule") for r in rows2)
    assert client.get(f"{API}/reviewers/{r['id']}").json()["used_items"] == 6  # exports don't count as reviewed


# --------------------------------------------------------------------------- deleting


def test_delete_exam_frees_its_items(client, fixture_files, session):
    from app.models import Answer, Attempt, Exam, Question, utcnow

    r, *_ = _ready_reviewer(client, fixture_files)
    e = make_exam(client, r["id"], {"types": ["mcq", "identification"], "count": 4})
    a = client.post(f"{API}/exams/{e['id']}/attempts").json()
    q = a["card"]["question"]
    client.post(f"{API}/attempts/{a['attempt_id']}/answer", json={"question_id": q["id"], "response": _wrong_answer(q)})
    assert client.get(f"{API}/reviewers/{r['id']}").json()["used_items"] == 4

    session.get(Exam, e["id"]).step_started_at = utcnow()  # being built right now -> refused
    session.commit()
    busy = client.delete(f"{API}/exams/{e['id']}")
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "ALREADY_PROCESSING"
    session.get(Exam, e["id"]).step_started_at = None
    session.commit()

    assert client.delete(f"{API}/exams/{e['id']}").status_code == 204
    assert client.get(f"{API}/exams/{e['id']}").status_code == 404
    assert client.get(f"{API}/attempts/{a['attempt_id']}").status_code == 404
    session.expire_all()
    assert session.query(Question).count() == 0 and session.query(Attempt).count() == 0 and session.query(Answer).count() == 0
    rv = client.get(f"{API}/reviewers/{r['id']}").json()
    assert rv["used_items"] == 0 and rv["exam_count"] == 0  # its items count as new again
    assert client.get(f"{API}/reviewers/{r['id']}/exams").json() == []
    assert client.delete(f"{API}/exams/{e['id']}").status_code == 404


def test_remove_file_with_delete_file(client, fixture_files):
    r, d1, d2 = _ready_reviewer(client, fixture_files)
    scope1 = {"documents": [{"document_id": d1["id"]}]}
    e1 = make_exam(client, r["id"], {"types": ["mcq"], "count": 3, "scope": scope1})
    e2 = make_exam(client, r["id"], {"types": ["mcq"], "count": 3, "scope": {"documents": [{"document_id": d2["id"]}]}})
    docs = {d["id"]: d for d in client.get(f"{API}/reviewers/{r['id']}").json()["documents"]}
    assert docs[d1["id"]]["exam_count"] == 1 and docs[d2["id"]]["exam_count"] == 1
    assert docs[d1["id"]]["shared"] is False

    # Plain remove keeps the file in the library and the exam working
    other = client.post(f"{API}/reviewers", json={"title": "Other", "document_ids": [d1["id"]]}).json()
    assert client.get(f"{API}/reviewers/{r['id']}").json()["documents"][0]["shared"] is True
    out = client.delete(f"{API}/reviewers/{r['id']}/documents/{d1['id']}?delete_file=true").json()
    assert out["deleted_file"] is False and out["deleted_exams"] == 0  # still used by "Other"
    assert client.get(f"{API}/documents/{d1['id']}").status_code == 200
    assert client.get(f"{API}/exams/{e1['id']}").status_code == 200

    # Not shared any more: deleting removes the file and the exams built from it
    client.post(f"{API}/reviewers/{r['id']}/documents", json={"document_id": d1["id"]})
    client.delete(f"{API}/reviewers/{other['id']}")
    out = client.delete(f"{API}/reviewers/{r['id']}/documents/{d1['id']}?delete_file=true").json()
    assert out["deleted_file"] is True and out["deleted_exams"] == 1 and out["document_count"] == 1
    assert client.get(f"{API}/documents/{d1['id']}").status_code == 404
    assert client.get(f"{API}/exams/{e1['id']}").status_code == 404
    assert client.get(f"{API}/exams/{e2['id']}").status_code == 200


def test_markdown_term_list_imports_without_gemini(client, tmp_path, fake_llm):
    from tests.test_ingestion import GLOSSARY

    md = tmp_path / "Terms.md"
    md.write_text(GLOSSARY, encoding="utf-8")
    d = upload(client, md)
    assert d["status"] == "ready" and d["file_type"] == "md" and d["page_unit"] == "section"
    assert d["item_count"] == 7 and d["items_by_kind"] == {"definition": 7, "fact": 0}
    assert fake_llm.calls == []  # no Gemini call for a term list
    r = client.post(f"{API}/reviewers", json={"title": "Terms", "document_ids": [d["id"]]}).json()
    e = make_exam(client, r["id"], {"types": ["identification"], "count": 3})
    assert e["status"] == "ready"
    a = client.post(f"{API}/exams/{e['id']}/attempts").json()
    fb = client.post(f"{API}/attempts/{a['attempt_id']}/answer",
                     json={"question_id": a["card"]["question"]["id"], "response": "x"}).json()["feedback"]
    assert fb["source"]["location"].startswith("section ")


def test_rebuild_without_gemini_when_time_is_short(client, fixture_files, fake_llm, monkeypatch):
    """Rejected questions are replaced even when there is no time for another Gemini call."""
    from app.services import llm as llm_mod
    from app.services.generation import exam_builder

    r, *_ = _ready_reviewer(client, fixture_files)
    real = exam_builder._apply_batch
    calls = {"n": 0}

    def flaky_apply(drafts, *a, **k):
        real(drafts, *a, **k)
        calls["n"] += 1
        if calls["n"] == 1:  # first round: pretend two questions failed the checks
            for d in drafts[:2]:
                d.failed = "forced"

    monkeypatch.setattr(exam_builder, "_apply_batch", flaky_apply)
    monkeypatch.setattr(llm_mod, "remaining_seconds", lambda: 30.0)  # too little for another Gemini call
    n_before = sum(1 for c in fake_llm.calls if c[0] == "GenerationBatch")
    e = make_exam(client, r["id"], {"types": ["mcq"], "count": 6})
    assert e["status"] == "ready" and e["actual_count"] == 6 and e["shortfall"] == 0
    assert sum(1 for c in fake_llm.calls if c[0] == "GenerationBatch") == n_before + 1  # no extra Gemini call
