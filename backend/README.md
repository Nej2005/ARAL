# ARAL — backend

Turns lesson files (PDF / PowerPoint) into exam-style reviewers. Runs on localhost only.
The full design is in [../BACKEND.md](../BACKEND.md).

## Run it

Requires Python 3.11 or newer and a free Gemini API key (Google AI Studio, no billing).

```powershell
cd backend
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -e ".[test]"
copy .env.example .env          # then put your key in GEMINI_API_KEY
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

- API: http://localhost:8000/api/v1 — interactive docs at http://localhost:8000/docs
- The SQLite database (`aral.db`) and uploaded files (`storage/`) are created next to this file on first start. Migrations run automatically.
- Old `.ppt` files need LibreOffice installed (`SOFFICE_PATH` in `.env`). PDF and `.pptx` need nothing extra.

## Test it

```powershell
.venv\Scripts\python -m pytest
```

The tests use a fake Gemini, so they are free and offline. For a live check against the real Gemini,
start the server and run `samples\smoke.py` (it uploads two small sample lessons, builds an exam and
answers every card). It uses about 3 free-tier calls.

## Layout

```
app/
  main.py            FastAPI app, CORS, migrations on startup
  config.py          settings from .env
  models/            SQLAlchemy tables (BACKEND.md §4)
  api/               routers: documents, reviewers, exams, attempts
  jobs.py            background jobs: extract a file, generate an exam
  services/
    ingestion/       pdf.py, pptx.py, ppt_convert.py, dedupe.py
    knowledge.py     pages -> source items with Gemini, validated against the page text
    fidelity.py      every "keep the lesson's wording" check
    generation/      selector, identification, multiple_choice, true_false, batch, exam_builder
    attempts.py      flashcards, grading, feedback, summary
    export/          printable exam PDF, study sheet PDF, Anki CSV
    llm.py           the only module that talks to Gemini
alembic/             database migrations
tests/               pytest suite with a fake Gemini (tests/fake_llm.py)
```

## Gemini free tier

- Rate limits are per minute and per day. The backend waits `LLM_MIN_SECONDS_BETWEEN_CALLS` between
  calls and retries on `429`. If the daily limit is hit, the file or exam shows `LLM_QUOTA_EXCEEDED`;
  `POST /documents/{id}/reprocess` later continues from the last saved window.
- Google may use free-tier prompts to improve its products. Don't upload confidential files.
