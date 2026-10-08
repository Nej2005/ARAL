import logging
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import attempts, documents, exams, reviewers
from app.config import BACKEND_DIR, settings
from app.db import engine
from app.errors import install_error_handlers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
for noisy in ("fontTools", "fontTools.subset", "fontTools.ttLib", "httpx", "httpcore", "google_genai"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
log = logging.getLogger("aral")


def run_migrations(db_url: str | None = None) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["configure_logging"] = False
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    url = db_url or settings.resolved_database_url()
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))  # configparser escaping
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.resolved_storage_dir().mkdir(parents=True, exist_ok=True)
    if not getattr(app.state, "skip_migrations", False):
        run_migrations(settings.resolved_database_url())
        from app.jobs import recover_interrupted

        recover_interrupted()
    if not settings.gemini_api_key:
        log.warning("GEMINI_API_KEY is empty: uploads will fail at the extraction step until it is set.")
    yield


app = FastAPI(title="ARAL API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)
install_error_handlers(app)

API = "/api/v1"
app.include_router(documents.router, prefix=API)
app.include_router(reviewers.router, prefix=API)
app.include_router(exams.router, prefix=API)
app.include_router(attempts.router, prefix=API)


@app.get(f"{API}/health")
def health():
    return {"ok": True, "model": settings.gemini_model, "has_api_key": bool(settings.gemini_api_key)}
