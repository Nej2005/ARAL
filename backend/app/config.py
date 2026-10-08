from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

import os

BACKEND_DIR = Path(__file__).resolve().parent.parent
ON_VERCEL = bool(os.environ.get("VERCEL"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    gemini_fallback_model: str = ""
    llm_min_seconds_between_calls: float = 6.0
    extraction_window_pages: int = 15

    database_url: str = "sqlite:///./aral.db"
    storage_dir: Path = Path("./storage")  # scratch space for temp files only
    max_upload_mb: int = 25
    upload_chunk_mb: int = 3  # under Vercel's 4.5 MB request limit
    step_claim_seconds: int = 150  # how long one processing step may hold a document / exam
    max_exam_items: int = 100
    ident_fuzzy_threshold: int = 90
    soffice_path: str = "soffice"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    app_passcode: str = ""  # empty = no passcode (fine on localhost); set it when the app is online

    @field_validator("gemini_fallback_model", "soffice_path", "gemini_model", mode="before")
    @classmethod
    def _strip_inline_comment(cls, v):
        # .env lines like `SOFFICE_PATH=soffice   # needed for .ppt only`
        if isinstance(v, str) and "#" in v:
            v = v.split("#", 1)[0]
        return v.strip() if isinstance(v, str) else v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def upload_chunk_bytes(self) -> int:
        return self.upload_chunk_mb * 1024 * 1024

    @property
    def database_kind(self) -> str:
        return "postgresql" if "postgres" in self.database_url else "sqlite"

    def resolved_storage_dir(self) -> Path:
        p = self.storage_dir
        if not p.is_absolute():
            # Serverless (Vercel): only /tmp is writable. Locally: next to the backend folder.
            p = (Path("/tmp/aral") if ON_VERCEL else BACKEND_DIR) / p
        return p

    def resolved_database_url(self) -> str:
        # Make a relative sqlite path relative to the backend folder (or /tmp on Vercel), not the CWD.
        url = self.database_url
        prefix = "sqlite:///./"
        if url.startswith(prefix):
            base = Path("/tmp/aral") if ON_VERCEL else BACKEND_DIR
            base.mkdir(parents=True, exist_ok=True)
            return "sqlite:///" + str((base / url[len(prefix):]).resolve()).replace("\\", "/")
        if url.startswith("postgres://"):  # common hosted-Postgres format -> SQLAlchemy + psycopg 3
            return "postgresql+psycopg://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            return "postgresql+psycopg://" + url[len("postgresql://"):]
        return url


settings = Settings()
