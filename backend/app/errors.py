from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    """An error with a stable code the frontend can map to a message.

    Responses look like: {"error": {"code": "...", "message": "...", ...extra}}
    """

    def __init__(self, status: int, code: str, message: str, **extra: Any):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra

    def payload(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, **self.extra}}


def not_found(what: str) -> AppError:
    return AppError(404, "NOT_FOUND", f"{what} not found.")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status, content=exc.payload())

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        errors = exc.errors()
        first = errors[0] if errors else {}
        loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        msg = first.get("msg", "Invalid request.")
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": f"{loc}: {msg}" if loc else msg,
                    "details": [
                        {"loc": e.get("loc"), "msg": e.get("msg")} for e in errors
                    ],
                }
            },
        )
