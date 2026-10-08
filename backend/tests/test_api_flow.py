"""The whole flow through the HTTP API with the fake Gemini (BACKEND.md §15 "API")."""

from __future__ import annotations

import csv
import io

from app.services import llm
from tests.conftest import upload
from tests.fixtures import build_pdf, build_pptx

API = "/api/v1"


def _ready_reviewer(client, fixture_files, title="Biology Midterm"):
    d1 = upload(client, fixture_files["pptx"]).json()
    d2 = upload(client, fixture_files["pdf"]).json()
    r = client.post(f"{API}/reviewers", json={"title": title, "document_ids": [d1["id"], d2["id"]]}).json()
    return r, d1, d2


def _answer_all(client, attempt_id, correct=True, skip_indexes=()):
    """Answer every card in order; returns the last response."""
    m = client.get(f"{API}/attempts/{attempt_id}").json()
    last = None
    for card in m["cards"]:
        if card["index"] in skip_indexes:
            continue
        c = client.get(f"{API}/attempts/{attempt_id}/cards/{card['index']}").json()
        q = c["question"]
        if correct:
            # The test needs the right answer: look it up from the DB-free route by answering wrong first? No:
            # we fetch it via the exam export answer key only in other tests; here use a deliberately wrong answer.
            resp = _wrong_answer(q)
        else:
            resp = _wrong_answer(q)
        last = client.post(f"{API}/attempts/{attempt_id}/answer", json={"question_id": q["id"], "response": resp})
        assert last.status_code == 200, last.text
    return last


def _wrong_answer(q):
    if q["type"] == "mcq":
        return q["choices"][0]["id"]  # may or may not be right; shuffled
    if q["type"] == "true_false":
        return "true"
    return "zzz-not-a-term"


# --------------------------------------------------------------------------- documents


def test_upload_extract_and_duplicates(client, fixture_files, fake_llm, tmp_path):
    r = upload(client, fixture_files["pptx"])
    assert r.status_code == 202 and r.json()["duplicate"] is False
    doc = client.get(f"{API}/documents/{r.json()['id']}").json()
    assert doc["status"] == "ready", doc
    assert doc["page_count"] == 5
    assert doc["item_count"] >= 10
    assert doc["items_by_kind"]["definition"] >= 8
    assert doc["outdated"] is False
    calls_after_first = len(fake_llm.calls)
    assert calls_after_first == 1  # 5 slides fit in one window

    # Same bytes again -> 200, duplicate, no Gemini call
    r2 = upload(client, fixture_files["pptx"])
    assert r2.status_code == 200 and r2.json()["duplicate"] is True and r2.json()["id"] == doc["id"]
    assert len(fake_llm.calls) == calls_after_first

    # Same text in a different file (new bytes) -> items copied, no Gemini call
    other = build_pptx(tmp_path / "again.pptx", variant="saved again")
    r3 = upload(client, other)
    assert r3.status_code == 202 and r3.json()["duplicate"] is False
    d3 = client.get(f"{API}/documents/{r3.json()['id']}").json()
    assert d3["status"] == "ready" and d3["copied_from_document_id"] == doc["id"]
    assert d3["item_count"] == doc["item_count"]
    assert len(fake_llm.calls) == calls_after_first

    assert len(client.get(f"{API}/documents").json()) == 2


def test_upload_rejects_bad_files(client, tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("hello")
    assert upload(client, bad).json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_bytes(b"not really a pdf")
    assert upload(client, fake_pdf).json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


def test_scanned_pdf_fails_cleanly_and_duplicate_failed_is_retried(client, tmp_path, fake_llm):
    from tests.fixtures import build_empty_pdf

    p = build_empty_pdf(tmp_path / "scan.pdf")
    r = upload(client, p)
    d = client.get(f"{API}/documents/{r.json()['id']}").json()
    assert d["status"] == "failed" and d["error_code"] == "NO_EXTRACTABLE_TEXT"
    r2 = upload(client, p)
    assert r2.status_code == 202 and r2.json()["duplicate"] is True  # re-extraction attempted


def test_quota_stop_resumes_where_it_left_off(client, tmp_path, fake_llm, monkeypatch):
    from app.config import settings
    from tests.fixtures import RESP_PAGES

    monkeypatch.setattr(settings, "extraction_window_pages", 2)  # 4 pages -> 3 windows (1-page overlap)
    pdf = build_pdf(tmp_path / "long.pdf")
    fake_llm.fail_with = None
    calls = {"n": 0}
    real = fake_llm.__call__

    def flaky(system, user, schema, label=""):
        calls["n"] += 1
        if calls["n"] == 2:
            raise llm.LLMQuotaExceeded("daily limit")
        return real(system, user, schema, label)

    llm.set_backend(flaky)
    r = upload(client, pdf)
    d = client.get(f"{API}/documents/{r.json()['id']}").json()
    assert d["status"] == "failed" and d["error_code"] == "LLM_QUOTA_EXCEEDED"
    assert d["extraction_progress"] == 1 and d["item_count"] > 0  # first window was saved

    rr = client.post(f"{API}/documents/{d['id']}/reprocess")
    assert rr.status_code == 202 and rr.json()["resumed"] is True
    d2 = client.get(f"{API}/documents/{d['id']}").json()
    assert d2["status"] == "ready"
    assert calls["n"] == 4  # 1 ok + 1 fail + 2 remaining windows (never redid window 1)
    assert d2["item_count"] >= len([l for _, ls in RESP_PAGES for l in ls]) - 2


def test_interrupted_jobs_are_recovered_at_startup(client, fixture_files, session):
    from app import jobs
    from app.models import Document, Exam

    r, d1, _ = _ready_reviewer(client, fixture_files)
    e = client.post(f"{API}/reviewers/{r['id']}/exams", json={"types": ["mcq"], "count": 2}).json()
    session.get(Document, d1["id"]).status = "extracting"
    session.get(Exam, e["id"]).status = "generating"
    session.commit()
    assert jobs.recover_interrupted() == 2
    d = client.get(f"{API}/documents/{d1['id']}").json()
    assert d["status"] == "failed" and d["error_code"] == "INTERRUPTED"
    assert client.get(f"{API}/exams/{e['id']}").json()["error_code"] == "INTERRUPTED"
    rr = client.post(f"{API}/documents/{d1['id']}/reprocess").json()
    assert rr["resumed"] is True  # keeps the windows already saved
    assert client.get(f"{API}/documents/{d1['id']}").json()["status"] == "ready"


def test_reprocess_supersedes_items_and_old_exams_still_render(client, fixture_files, fake_llm):
    r, d1, d2 = _ready_reviewer(client, fixture_files)
    e = client.post(f"{API}/reviewers/{r['id']}/exams", json={"types": ["identification"], "count": 3}).json()
    assert client.get(f"{API}/exams/{e['id']}").json()["status"] == "ready"
    before = client.get(f"{API}/reviewers/{r['id']}").json()
    assert before["used_items"] == 3
    assert client.post(f"{API}/documents/{d1['id']}/reprocess").status_code == 202
    after = client.get(f"{API}/reviewers/{r['id']}").json()
    assert after["item_count"] == before["item_count"]
    # new items have new ids -> the ones used from d1 no longer count as used
    assert after["used_items"] <= before["used_items"]
    a = client.post(f"{API}/exams/{e['id']}/attempts").json()
    assert a["card"]["question"]["prompt"]


# --------------------------------------------------------------------------- reviewers


def test_reviewer_crud_outline_and_document_rules(client, fixture_files):
    r, d1, d2 = _ready_reviewer(client, fixture_files)
    assert r["document_count"] == 2 and r["status"] == "ready" and r["used_items"] == 0
    lst = client.get(f"{API}/reviewers").json()
    assert lst[0]["id"] == r["id"]

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
    d = upload(client, fixture_files["pdf"]).json()
    assert client.get(f"{API}/documents/{d['id']}").json()["status"] == "failed"
    r = client.post(f"{API}/reviewers", json={"title": "X", "document_ids": [d["id"]]}).json()
    assert r["status"] == "needs_attention"
    e = client.post(f"{API}/reviewers/{r['id']}/exams", json={"types": ["mcq"], "count": 5})
    assert e.status_code == 409 and e.json()["error"]["code"] == "DOCUMENTS_NOT_READY"


# --------------------------------------------------------------------------- exams + flashcards


def test_full_exam_flow(client, fixture_files, fake_llm):
    r, d1, d2 = _ready_reviewer(client, fixture_files)
    av = client.post(f"{API}/reviewers/{r['id']}/availability", json={"types": ["mcq", "true_false", "identification"]}).json()
    assert av["unused_items"] == av["total_items"] >= 20 and av["unused_outside_scope"] == 0

    e = client.post(f"{API}/reviewers/{r['id']}/exams", json={"types": ["mcq", "true_false", "identification"], "count": 9})
    assert e.status_code == 202
    exam = client.get(f"{API}/exams/{e.json()['id']}").json()
    assert exam["status"] == "ready", exam
    assert exam["actual_count"] == 9 and exam["shortfall"] == 0
    assert sum(1 for c in fake_llm.calls if c[0] == "GenerationBatch") == 1  # one batched call

    # coverage: 9 items now used
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

    # Skip card 1, answer card 2
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

    # Answer is final
    again = client.post(f"{API}/attempts/{aid}/answer", json={"question_id": q2["id"], "response": "x"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "ALREADY_ANSWERED"
    # Going back shows the saved feedback
    back = client.get(f"{API}/attempts/{aid}/cards/2").json()
    assert back["answered"] is True and back["feedback"] == f

    # Answer the rest except card 1, then the wrap-around points back to 1
    last = None
    for i in range(3, 10):
        q = client.get(f"{API}/attempts/{aid}/cards/{i}").json()["question"]
        last = client.post(f"{API}/attempts/{aid}/answer", json={"question_id": q["id"], "response": _wrong_answer(q)}).json()
    assert last["finished"] is False and last["next_unanswered_index"] == 1
    assert client.get(f"{API}/attempts/{aid}/summary").json()["error"]["code"] == "ATTEMPT_NOT_FINISHED"
    assert client.get(f"{API}/attempts/{aid}/cards/99").status_code == 404

    # Finish with card 1 skipped
    s = client.post(f"{API}/attempts/{aid}/finish").json()
    assert s["total"] == 9 and s["answered"] == 8 and s["skipped"] == 1
    assert s["correct_count"] + len(s["wrong_cards"]) + len(s["skipped_cards"]) == 9
    assert s["retry_mistakes"]["count"] == len(s["wrong_cards"]) + 1
    assert s["next_set"]["unused_items"] == av["total_items"] - 9
    skipped = s["skipped_cards"][0]
    assert skipped["your_answer"] is None and skipped["correct_answer"]["text"]
    assert client.post(f"{API}/attempts/{aid}/answer", json={"question_id": q2["id"], "response": "x"}).json()["error"]["code"] == "ATTEMPT_COMPLETED"

    # Retry mistakes: exactly the wrong + skipped cards, no coverage change, no LLM call
    n_calls = len(fake_llm.calls)
    rm = client.post(f"{API}/attempts/{aid}/retry-mistakes")
    assert rm.status_code == 201 and rm.json()["kind"] == "mistakes"
    assert rm.json()["total"] == s["retry_mistakes"]["count"]
    assert len(fake_llm.calls) == n_calls
    assert client.get(f"{API}/reviewers/{r['id']}").json()["used_items"] == 9
    rid = rm.json()["attempt_id"]
    assert client.post(f"{API}/attempts/{rid}/retry-mistakes").json()["error"]["code"] == "ATTEMPT_NOT_FINISHED"

    # Restart: same questions, new attempt number
    rs = client.post(f"{API}/exams/{exam['id']}/attempts").json()
    assert rs["attempt_no"] == 3 and rs["total"] == 9
    lst = client.get(f"{API}/reviewers/{r['id']}/exams").json()
    assert lst[0]["id"] == exam["id"] and lst[0]["attempt_count"] == 3 and lst[0]["best_score"]["total"] == 9


def test_answers_graded_correctly_with_known_answers(client, fixture_files, session):
    """Answer with the real correct answers (read from the DB) and check perfect score + NO_MISTAKES."""
    from app.models import Question

    r, *_ = _ready_reviewer(client, fixture_files)
    e = client.post(f"{API}/reviewers/{r['id']}/exams", json={"types": ["mcq", "true_false", "identification"], "count": 6}).json()
    att = client.post(f"{API}/exams/{e['id']}/attempts").json()
    aid = att["attempt_id"]
    for i in range(1, 7):
        card = client.get(f"{API}/attempts/{aid}/cards/{i}").json()
        q = session.get(Question, card["question"]["id"])
        resp = q.correct_answer if q.type != "identification" else q.correct_answer.upper() + "  "  # case/space tolerant
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
    e = client.post(f"{API}/reviewers/{r['id']}/exams", json={"types": ["identification"], "count": 6}).json()
    aid = client.post(f"{API}/exams/{e['id']}/attempts").json()["attempt_id"]
    card = client.get(f"{API}/attempts/{aid}/cards/1").json()
    q = session.get(Question, card["question"]["id"])
    other = session.query(SourceItem).filter(SourceItem.id != q.source_item_id, SourceItem.term.isnot(None)).first()
    out = client.post(f"{API}/attempts/{aid}/answer", json={"question_id": q.id, "response": other.term}).json()
    assert out["feedback"]["is_correct"] is False
    assert out["feedback"]["why_yours_is_wrong"].startswith(f"'{other.term}' is a different concept")

    # A one-letter typo is tolerated on a term long enough for it to stay a >= 90% match.
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

    bad = client.post(f"{API}/reviewers/{r['id']}/exams",
                      json={"types": ["mcq"], "count": 3, "scope": {"documents": [{"document_id": d1["id"], "pages": [[1, 99]]}]}})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "INVALID_SCOPE"

    scope = {"documents": [{"document_id": d1["id"]}]}
    av = client.post(f"{API}/reviewers/{r['id']}/availability", json={"types": ["mcq"], "scope": scope}).json()
    assert av["unused_items"] == pptx_items and av["unused_outside_scope"] == av["total_items"] - pptx_items

    e1 = client.post(f"{API}/reviewers/{r['id']}/exams", json={"types": ["mcq"], "count": pptx_items, "scope": scope}).json()
    e1 = client.get(f"{API}/exams/{e1['id']}").json()
    assert e1["status"] == "ready" and e1["actual_count"] == pptx_items and e1["scope"] == scope

    # Everything inside the scope is used: next set inherits the scope -> 409 with items outside
    ns = client.post(f"{API}/exams/{e1['id']}/next-set")
    assert ns.status_code == 409 and ns.json()["error"]["code"] == "ALL_ITEMS_REVIEWED"
    assert ns.json()["error"]["unused_outside_scope"] == av["total_items"] - pptx_items

    # Explicit null scope widens to the whole reviewer, and asks for more than is left -> shortfall
    ns2 = client.post(f"{API}/exams/{e1['id']}/next-set", json={"scope": None, "count": 99})
    assert ns2.status_code == 202 and ns2.json()["parent_exam_id"] == e1["id"]
    e2 = client.get(f"{API}/exams/{ns2.json()['id']}").json()
    assert e2["status"] == "ready" and e2["scope"] is None
    assert e2["actual_count"] == av["total_items"] - pptx_items and e2["shortfall"] == 99 - e2["actual_count"]

    assert client.post(f"{API}/reviewers/{r['id']}/exams", json={"types": ["mcq"], "count": 1}).json()["error"]["code"] == "ALL_ITEMS_REVIEWED"
    assert client.post(f"{API}/reviewers/{r['id']}/coverage/reset").json()["coverage_epoch"] == 1
    assert client.get(f"{API}/reviewers/{r['id']}").json()["unused_items"] == av["total_items"]
    assert client.post(f"{API}/reviewers/{r['id']}/exams", json={"types": ["mcq"], "count": 1}).status_code == 202
    # old exam still intact
    assert client.get(f"{API}/exams/{e1['id']}").json()["actual_count"] == pptx_items


def test_adding_a_document_later_adds_unused_items(client, fixture_files):
    d1 = upload(client, fixture_files["pptx"]).json()
    r = client.post(f"{API}/reviewers", json={"title": "One file", "document_ids": [d1["id"]]}).json()
    e = client.post(f"{API}/reviewers/{r['id']}/exams", json={"types": ["true_false"], "count": 100}).json()
    assert client.get(f"{API}/exams/{e['id']}").json()["actual_count"] == r["item_count"]
    assert client.get(f"{API}/reviewers/{r['id']}").json()["unused_items"] == 0
    d2 = upload(client, fixture_files["pdf"], reviewer_id=r["id"]).json()
    rr = client.get(f"{API}/reviewers/{r['id']}").json()
    assert rr["document_count"] == 2 and rr["unused_items"] > 0
    assert d2["id"] in [d["id"] for d in rr["documents"]]


def test_generation_failure_is_reported_on_the_exam(client, fixture_files, fake_llm):
    r, *_ = _ready_reviewer(client, fixture_files)
    fake_llm.fail_with = llm.LLMQuotaExceeded("limit")
    e = client.post(f"{API}/reviewers/{r['id']}/exams", json={"types": ["mcq"], "count": 3}).json()
    ex = client.get(f"{API}/exams/{e['id']}").json()
    assert ex["status"] == "failed" and ex["error_code"] == "LLM_QUOTA_EXCEEDED"
    assert client.post(f"{API}/exams/{e['id']}/attempts").json()["error"]["code"] == "EXAM_NOT_READY"
    assert client.get(f"{API}/reviewers/{r['id']}").json()["used_items"] == 0  # failed exams don't use items


def test_bad_rationale_falls_back_to_template(client, fixture_files, fake_llm, session):
    from app.models import Question

    fake_llm.bad_rationale_for = {"q1", "q2", "q3"}
    r, *_ = _ready_reviewer(client, fixture_files)
    e = client.post(f"{API}/reviewers/{r['id']}/exams", json={"types": ["identification"], "count": 3}).json()
    qs = session.query(Question).filter(Question.exam_id == e["id"]).all()
    assert len(qs) == 3 and all(q.rationale.startswith("The lesson states: '") for q in qs)


# --------------------------------------------------------------------------- export


def test_exports(client, fixture_files):
    r, d1, d2 = _ready_reviewer(client, fixture_files)
    e = client.post(f"{API}/reviewers/{r['id']}/exams", json={"types": ["mcq", "true_false", "identification"], "count": 6}).json()

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
    # exports do not count as reviewed
    assert client.get(f"{API}/reviewers/{r['id']}").json()["used_items"] == 6
