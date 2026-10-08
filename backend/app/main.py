import hmac
import logging
from contextlib import asynccontextmanager

from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import attempts, documents, exams, reviewers, uploads
from app.config import BACKEND_DIR, ON_VERCEL, settings
from app.errors import install_error_handlers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
for noisy in ("fontTools", "fontTools.subset", "fontTools.ttLib", "httpx", "httpcore", "google_genai"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
log = logging.getLogger("aral")

API = "/api/v1"


def run_migrations(db_url: str | None = None) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["configure_logging"] = False
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    url = db_url or settings.resolved_database_url()
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))  # configparser escaping
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not getattr(app.state, "skip_migrations", False):
        run_migrations(settings.resolved_database_url())
        from app.jobs import clear_stale_claims

        clear_stale_claims()
    if not settings.gemini_api_key:
        log.warning("GEMINI_API_KEY is empty: files will fail at the extraction step until it is set.")
    if ON_VERCEL and settings.database_kind != "postgresql":
        log.error("Running on Vercel without a PostgreSQL DATABASE_URL: data will not persist between requests.")
    if ON_VERCEL and not settings.app_passcode:
        log.warning("APP_PASSCODE is empty: anyone with the URL can use your Gemini quota.")
    yield


app = FastAPI(title="ARAL API", version="0.2.0", lifespan=lifespan)


@app.middleware("http")
async def passcode_guard(request: Request, call_next):
    """When APP_PASSCODE is set, every API route except /health needs the X-Passcode header."""
    path = request.url.path
    if settings.app_passcode and path.startswith(API) and path != f"{API}/health" and request.method != "OPTIONS":
        supplied = request.headers.get("x-passcode") or request.query_params.get("passcode") or ""
        if not hmac.compare_digest(supplied.encode(), settings.app_passcode.encode()):
            code = "PASSCODE_WRONG" if supplied else "PASSCODE_REQUIRED"
            return JSONResponse(status_code=401, content={"error": {"code": code, "message": "Passcode needed."}})
    return await call_next(request)


# Added after the guard so CORS is the outer layer: 401s from the guard still get CORS headers.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)
install_error_handlers(app)


app.include_router(documents.router, prefix=API)
app.include_router(uploads.router, prefix=API)
app.include_router(reviewers.router, prefix=API)
app.include_router(exams.router, prefix=API)
app.include_router(attempts.router, prefix=API)


@app.get(f"{API}/health")
def health():
    return {
        "ok": True,
        "model": settings.gemini_model,
        "has_api_key": bool(settings.gemini_api_key),
        "passcode_required": bool(settings.app_passcode),
        "database": settings.database_kind,
        "on_vercel": ON_VERCEL,
        "upload_chunk_bytes": settings.upload_chunk_bytes,
        "max_upload_bytes": settings.max_upload_bytes,
        "warning": ("Set DATABASE_URL to a PostgreSQL database on Vercel"
                    if ON_VERCEL and settings.database_kind != "postgresql" else None),
    }
