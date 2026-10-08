"""Request bodies (BACKEND.md §12). Responses are plain dicts built in the routers."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

QuestionType = Literal["mcq", "true_false", "identification"]


class ScopeDocument(BaseModel):
    document_id: str
    pages: list[tuple[int, int]] | None = None


class Scope(BaseModel):
    documents: list[ScopeDocument] | None = None
    topics: list[str] | None = None


class CreateReviewer(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    document_ids: list[str] = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title must not be empty")
        return v


class PatchReviewer(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    document_order: list[str] | None = None


class AddDocument(BaseModel):
    document_id: str


class AvailabilityRequest(BaseModel):
    types: list[QuestionType] = Field(default_factory=lambda: ["mcq", "true_false", "identification"])
    scope: Scope | None = None


class ExportRequest(BaseModel):
    format: Literal["pdf", "csv"]
    scope: Scope | None = None


class CreateExam(BaseModel):
    types: list[QuestionType] = Field(min_length=1)
    count: int | None = Field(default=None, ge=1)  # required unless all_items
    scope: Scope | None = None
    all_items: bool = False  # every item in the scope (reviewed or not), hints kept as small as possible

    @model_validator(mode="after")
    def _count_needed(self):
        if self.count is None and not self.all_items:
            raise ValueError("count is required")
        return self

    @field_validator("types")
    @classmethod
    def _unique(cls, v):
        out = []
        for t in v:
            if t not in out:
                out.append(t)
        return out


class NextSet(BaseModel):
    types: list[QuestionType] | None = None
    count: int | None = Field(default=None, ge=1)
    scope: Scope | None = None


class AnswerRequest(BaseModel):
    question_id: str
    response: str = Field(max_length=500)


class StartUpload(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(ge=1)
    sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")
    reviewer_id: str | None = None


class CompleteUpload(BaseModel):
    reviewer_id: str | None = None
