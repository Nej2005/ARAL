"""Live end-to-end run against the running server (and the real Gemini). Prints what it sees."""

import sys
import time
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles otherwise mangle en-dashes

API = "http://127.0.0.1:8000/api/v1"
HERE = Path(__file__).parent
c = httpx.Client(timeout=60)


def drive(url, limit=240):
    """Call POST .../process until the document / exam is ready or failed (what the frontend does)."""
    t0 = time.time()
    while time.time() - t0 < limit:
        r = c.post(url + "/process").json()
        if r.get("done"):
            return r
        time.sleep(0.5)
    raise SystemExit(f"timeout processing {url}: {r}")


print("health:", c.get(f"{API}/health").json())
ids = []
for name in ("Lesson 3 - Photosynthesis.pptx", "Lesson 4 - Cellular Respiration.pdf"):
    with open(HERE / name, "rb") as f:
        r = c.post(f"{API}/documents", files={"file": (name, f)})
    print("upload", name, r.status_code, r.json().get("duplicate"))
    ids.append(r.json()["id"])

for did in ids:
    d = drive(f"{API}/documents/{did}")
    print(f"doc {d['filename']}: {d['status']} pages={d['page_count']} items={d['item_count']} "
          f"kinds={d['items_by_kind']} err={d.get('error_code')} {d.get('error_message') or ''}")
    if d["status"] != "ready":
        sys.exit("extraction failed")

rv = c.post(f"{API}/reviewers", json={"title": "Biology Midterm", "document_ids": ids}).json()
print("reviewer:", rv["title"], rv["status"], "items", rv["item_count"])
csv_text = c.post(f"{API}/reviewers/{rv['id']}/export", json={"format": "csv"}).text
print("--- extracted items (first 12 CSV rows) ---")
for line in csv_text.splitlines()[6:18]:
    print("  ", line[:160])
out = c.get(f"{API}/reviewers/{rv['id']}/outline").json()
print("topics:", [t["topic"] for t in out["topics"]])
av = c.post(f"{API}/reviewers/{rv['id']}/availability", json={"types": ["mcq", "true_false", "identification"]}).json()
print("availability:", av)

e = c.post(f"{API}/reviewers/{rv['id']}/exams", json={"types": ["mcq", "true_false", "identification"], "count": 6})
print("exam create:", e.status_code, e.json().get("id") or e.json())
ex = drive(f"{API}/exams/{e.json()['id']}")
print("exam:", ex["status"], "actual", ex["actual_count"], "shortfall", ex["shortfall"], ex.get("error_code"), ex.get("error_message") or "")
if ex["status"] != "ready":
    sys.exit("generation failed")

a = c.post(f"{API}/exams/{ex['id']}/attempts").json()
aid = a["attempt_id"]
print(f"\n=== attempt {a['attempt_no']} ({a['total']} cards) ===")
for i in range(1, a["total"] + 1):
    card = c.get(f"{API}/attempts/{aid}/cards/{i}").json()
    q = card["question"]
    print(f"\n[{i}] {q['type'].upper()}: {q['prompt']}")
    if q["type"] == "mcq":
        for k, ch in enumerate(q["choices"]):
            print(f"      {'ABCD'[k]}. {ch['text']}")
        resp = q["choices"][0]["id"]
    elif q["type"] == "true_false":
        resp = "true"
    else:
        resp = "Photosynthesis"
    fb = c.post(f"{API}/attempts/{aid}/answer", json={"question_id": q["id"], "response": resp}).json()
    f = fb["feedback"]
    print(f"    -> {'CORRECT' if f['is_correct'] else 'WRONG'}; answer: {f['correct_answer']['text']}")
    print(f"       why: {f['why']}")
    if f["why_yours_is_wrong"]:
        print(f"       why yours is wrong: {f['why_yours_is_wrong']}")
    if f["changed_span"]:
        print(f"       changed: {f['changed_span']}")
    print(f"       source: {f['source']['filename']}, {f['source']['location']}: \"{f['source']['quote'][:90]}\"")

s = c.get(f"{API}/attempts/{aid}/summary").json()
print(f"\nsummary: {s['correct_count']}/{s['total']} ({s['percent']}%), wrong={len(s['wrong_cards'])}, "
      f"skipped={s['skipped']}, retry={s['retry_mistakes']}, next_set={s['next_set']}")
if s["retry_mistakes"]["count"]:
    rm = c.post(f"{API}/attempts/{aid}/retry-mistakes").json()
    print("retry mistakes:", rm["kind"], rm["total"], "cards")
pdf = c.get(f"{API}/exams/{ex['id']}/export?format=pdf")
(HERE / "exam.pdf").write_bytes(pdf.content)
sheet = c.post(f"{API}/reviewers/{rv['id']}/export", json={"format": "pdf"})
(HERE / "study-sheet.pdf").write_bytes(sheet.content)
print("exports:", pdf.status_code, len(pdf.content), "bytes;", sheet.status_code, len(sheet.content), "bytes")
print("exams list:", c.get(f"{API}/reviewers/{rv['id']}/exams").json()[0]["best_score"])
