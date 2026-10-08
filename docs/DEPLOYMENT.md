# Deploying ARAL to Vercel

**Live:** https://aral-psi.vercel.app (Vercel project `aral`, database: Neon project `ARAL`, branch `production`).
Every push to `main` on GitHub redeploys it. The passcode is in `backend/.env` as `APP_PASSCODE_VERCEL` (never committed).

One Vercel project serves the React frontend as static files and the FastAPI backend as a Python
serverless function on the same domain. Data lives in a hosted PostgreSQL (free tier is enough).

## Day-to-day (CLI, already logged in on this PC)

```powershell
vercel --prod            # deploy the working copy now (a git push does this too)
vercel env ls production # see which variables are set
vercel logs https://aral-psi.vercel.app   # recent function logs
neon connection-string production --project-id snowy-boat-72279711 --pooled   # the DATABASE_URL
```

## How it fits a serverless host

| Concern | How ARAL handles it |
|---|---|
| No permanent disk | Uploaded files are stored in the database (table `document_files`) and deleted once their pages are read. No file storage service is needed. |
| 4.5 MB request limit | The browser uploads files in 3 MB chunks (`POST /uploads` → `PUT /uploads/{id}/chunks/{n}` → `complete`). Duplicates are detected from the file's hash before any bytes are sent. |
| No background jobs | Processing happens in steps: the open browser tab calls `POST /documents/{id}/process` (one Gemini window per call) and `POST /exams/{id}/process` until the status is `ready`. Progress is saved after every step; closing the tab just pauses. |
| Public URL | `APP_PASSCODE` protects every API route; the app asks for it once per browser. |
| SQLite is local-only | `DATABASE_URL` pointing at PostgreSQL. The migrations run automatically on the first request. |

Local development is unchanged (SQLite, no passcode).

## Files involved

| File | Purpose |
|---|---|
| `vercel.json` | Builds `frontend/` into `frontend/dist`, routes `/api/*` to the Python function, sends every other path to the React app, sets the function timeout |
| `api/index.py` | Serverless entry point; imports the FastAPI app from `backend/` |
| `requirements.txt` | Python packages for the function (includes the PostgreSQL driver) |
| `.vercelignore` | Leaves out virtual envs, local data, tests and design files |
| `frontend/.env.production` | Production builds call the API on the same domain (`/api/v1`) |

## Deploy steps

### 1. Create a free PostgreSQL database
1. Sign up at **neon.tech** (or supabase.com) and create a project.
2. Copy the connection string. It looks like `postgresql://user:password@host/dbname?sslmode=require`.

### 2. Create the Vercel project
1. Sign in at **vercel.com** with your GitHub account.
2. **Add New → Project → Import** `Nej2005/ARAL`.
3. Leave *Root Directory* as the repository root and *Framework Preset* as **Other**. `vercel.json` provides the build settings.
4. Under **Environment Variables**, add:

| Variable | Value |
|---|---|
| `GEMINI_API_KEY` | your Gemini key |
| `DATABASE_URL` | the connection string from step 1 |
| `APP_PASSCODE` | a passcode you choose (the app will ask for it) |
| `LLM_MIN_SECONDS_BETWEEN_CALLS` | `1` |

5. **Deploy.**

### 3. Check it
- Open `https://<your-project>.vercel.app/api/v1/health`. It should show `"database": "postgresql"` and `"passcode_required": true`.
- Open `https://<your-project>.vercel.app`, enter the passcode, and upload a lesson.

### 4. Updates
Every push to `main` on GitHub redeploys automatically.

## Known limits online

- **Keep the tab open** while a file is being read. Processing continues only while the page is open; it resumes where it stopped when you come back.
- **Function timeout.** `vercel.json` asks for 300 seconds per call. If your plan allows less, lower `maxDuration` (60 is fine: one step is a single Gemini call, usually 5–20 s).
- **Old `.ppt` files** can't be converted online (no LibreOffice). Save them as `.pptx` first.
- **Free Gemini quota** is shared by everyone who has the passcode.
- **Database size.** Free PostgreSQL tiers hold about 0.5 GB. Uploaded bytes are deleted after reading, so only text is kept long-term.
