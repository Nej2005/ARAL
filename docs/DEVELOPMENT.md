# Running ARAL locally

## First time

```powershell
# backend (Python 3.11+)
cd backend
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -e ".[test]"
copy .env.example .env        # put your free Gemini key (Google AI Studio) in GEMINI_API_KEY

# frontend (Node 18+)
cd ..\frontend
npm install
```

## Every time (two terminals)

```powershell
# 1 · backend → http://localhost:8000  (API docs at /docs)
cd backend
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000

# 2 · frontend → http://localhost:5173
cd frontend
npm run dev
```

Open **http://localhost:5173**. Stop either server with **Ctrl + C**.

The SQLite database (`backend/aral.db`) and uploaded files (`backend/storage/`) are created on first start.

## Checks

| What | Command |
|---|---|
| Backend tests (offline, fake Gemini) | `cd backend` → `.venv\Scripts\python -m pytest` |
| Frontend type-check | `cd frontend` → `npm run typecheck` |
| Frontend production build | `cd frontend` → `npm run build` |
| Live API smoke test (server running, ~3 Gemini calls) | `cd backend` → `.venv\Scripts\python samples\smoke.py` |
| Full browser click-through (both servers running) | `cd frontend` → `node e2e/flow.mjs` (screenshots → `design/screenshots/`) |

For the browser check, install Chromium once: `npx playwright install chromium`.

To run the backend tests against PostgreSQL instead of SQLite, set `TEST_DATABASE_URL=postgresql://…`
(the `pgserver` package can provide a throwaway local Postgres).

## Optional settings

- `APP_PASSCODE` in `backend/.env`: when set, the app asks for the passcode once per browser.
  Leave it empty on localhost.
- Processing (reading files, building exams) runs in steps driven by the open browser tab.
  If you close the tab mid-way, it continues the next time you open the reviewer.
