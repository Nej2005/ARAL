# Deploying ARAL to Vercel (later)

ARAL runs locally today. The repository is already **laid out for Vercel**: one project serves the React
frontend as static files and the FastAPI backend as a Python serverless function on the same domain.
A few backend changes are still needed before it works well there; they're listed below.

## What is already prepared

| File | Purpose |
|---|---|
| `vercel.json` | Builds `frontend/` into `frontend/dist`, routes `/api/*` to the Python function, and sends every other path to the React app |
| `api/index.py` | Serverless entry point; imports the FastAPI app from `backend/` |
| `requirements.txt` | Python packages for the function (adds the PostgreSQL driver) |
| `.vercelignore` | Leaves out virtual envs, local data, tests and design files |
| `frontend/.env.production` | Production builds call the API on the same domain (`/api/v1`) |
| `backend/app/config.py` | On Vercel, local files and SQLite go to `/tmp`; `DATABASE_URL=postgres://…` is converted for SQLAlchemy automatically |

Local development is unchanged: none of these files are used by `uvicorn` or `npm run dev`.

## Environment variables to set in Vercel

| Variable | Value |
|---|---|
| `GEMINI_API_KEY` | your Gemini key |
| `DATABASE_URL` | a hosted PostgreSQL URL (e.g. Neon or Supabase, both have free tiers) |
| `CORS_ORIGINS` | your Vercel URL, e.g. `https://aral.vercel.app` (only needed if the frontend is served from another domain) |
| `LLM_MIN_SECONDS_BETWEEN_CALLS` | `0`–`2` (each function call is short-lived) |

## Still to do before it works on Vercel

These come from how serverless functions behave, not from bugs in ARAL:

1. **Database.** The function's disk is temporary, so SQLite in `/tmp` is wiped between runs. Set
   `DATABASE_URL` to a hosted PostgreSQL. The models and migrations already work with PostgreSQL.
2. **Uploaded files.** `backend/storage/` lives on disk. Move uploads to object storage (e.g. Vercel Blob)
   and upload from the browser directly to it, because Vercel limits request bodies to about **4.5 MB**.
3. **Background jobs.** Extraction and exam generation run after the response is sent. On serverless
   this work can be cut off when the response ends. Run them through a queue/worker, or process in the
   request with a longer `maxDuration` (Pro plan) and poll for status.
4. **Time limits.** A large file may take longer than one function call allows. Extraction already saves
   progress per window, so it can be resumed in several calls.
5. **Old `.ppt` files.** LibreOffice is not available on Vercel; accept PDF and `.pptx` only there.
6. **Privacy.** Once online, anyone with the URL could use your Gemini quota. Add a login or a shared
   passcode first.

## Deploy steps (when ready)

1. Push the repository to GitHub.
2. In Vercel: **Add New → Project →** import the repository. Leave the root directory as the repo root;
   `vercel.json` provides the build settings.
3. Add the environment variables above, then deploy.
4. Open `https://<your-project>.vercel.app/api/v1/health` to check that the backend answers.
