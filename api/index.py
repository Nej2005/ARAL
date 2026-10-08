"""Vercel serverless entry point: exposes the FastAPI app from backend/ as an ASGI function.

Vercel routes /api/* here (see vercel.json); the app itself serves everything under /api/v1.
Not used for local development (run uvicorn in backend/ instead).
"""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app.main import app  # noqa: E402,F401
