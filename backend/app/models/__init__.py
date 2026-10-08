import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- documents


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("owner_id", "sha256", name="uq_documents_owner_sha"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    owner_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    filename: Mapped[str] = mapped_column(Text)
    file_type: Mapped[str] = mapped_column(String(8))  # pdf | pptx | ppt | md | txt
    storage_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    text_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    extraction_version: Mapped[int] = mapped_column(Integer, default=0)
    copied_from_document_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    extraction_progress: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="uploaded")  # uploaded|extracting|ready|failed
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    size: Mapped[int] = mapped_column(Integer, default=0)
    # Set while one request is running a processing step; lets concurrent callers back off (jobs.py).
    step_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    pages: Mapped[list["DocumentPage"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentPage.page_no"
    )
    file: Mapped["DocumentFile | None"] = relationship(
        back_populates="document", cascade="all, delete-orphan", uselist=False
    )
    items: Mapped[list["SourceItem"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    reviewer_links: Mapped[list["ReviewerDocument"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    @property
    def page_unit(self) -> str:
        if self.file_type in ("pptx", "ppt"):
            return "slide"
        if self.file_type in ("md", "txt"):
            return "section"
        return "page"

    def page_label(self, page_no: int) -> str:
        unit = self.page_unit
        return f"slide {page_no}" if unit == "slide" else f"section {page_no}" if unit == "section" else f"p. {page_no}"


class DocumentFile(Base):
    """The uploaded bytes, kept in the database so the app has no disk dependency.

    Deleted once the pages have been read: everything after that works from `document_pages`.
    """

    __tablename__ = "document_files"

    document_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    data: Mapped[bytes] = mapped_column(LargeBinary)
    size: Mapped[int] = mapped_column(Integer)

    document: Mapped[Document] = relationship(back_populates="file")


class UploadSession(Base):
    """A chunked upload in progress (BACKEND.md §5.1). Chunks are assembled on complete."""

    __tablename__ = "upload_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    owner_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    filename: Mapped[str] = mapped_column(Text)
    file_type: Mapped[str] = mapped_column(String(8))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    chunk_size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    chunks: Mapped[list["UploadChunk"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="UploadChunk.index"
    )


class UploadChunk(Base):
    __tablename__ = "upload_chunks"

    upload_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("upload_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    index: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary)

    session: Mapped[UploadSession] = relationship(back_populates="chunks")


class DocumentPage(Base):
    __tablename__ = "document_pages"
    __table_args__ = (UniqueConstraint("document_id", "page_no", name="uq_pages_doc_page"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    page_no: Mapped[int] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    text: Mapped[str] = mapped_column(Text)

    document: Mapped[Document] = relationship(back_populates="pages")


class SourceItem(Base):
    __tablename__ = "source_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    page_no: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))  # definition | fact
    term: Mapped[str | None] = mapped_column(Text, nullable=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    body: Mapped[str] = mapped_column(Text)
    source_quote: Mapped[str] = mapped_column(Text)
    quote_start: Mapped[int] = mapped_column(Integer, default=0)
    quote_end: Mapped[int] = mapped_column(Integer, default=0)
    topic: Mapped[str | None] = mapped_column(Text, nullable=True)
    topic_key: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped[Document] = relationship(back_populates="items")


# ---------------------------------------------------------------- reviewers


class Reviewer(Base):
    __tablename__ = "reviewers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    owner_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str] = mapped_column(Text)
    coverage_epoch: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    links: Mapped[list["ReviewerDocument"]] = relationship(
        back_populates="reviewer",
        cascade="all, delete-orphan",
        order_by="ReviewerDocument.position",
    )
    exams: Mapped[list["Exam"]] = relationship(
        back_populates="reviewer", cascade="all, delete-orphan"
    )

    @property
    def documents(self) -> list[Document]:
        return [l.document for l in self.links]


class ReviewerDocument(Base):
    __tablename__ = "reviewer_documents"

    reviewer_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("reviewers.id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    reviewer: Mapped[Reviewer] = relationship(back_populates="links")
    document: Mapped[Document] = relationship(back_populates="reviewer_links")


# ---------------------------------------------------------------- exams


class Exam(Base):
    __tablename__ = "exams"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    reviewer_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("reviewers.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    question_types: Mapped[list] = mapped_column(JSON, default=list)
    requested_count: Mapped[int] = mapped_column(Integer)
    actual_count: Mapped[int] = mapped_column(Integer, default=0)
    scope: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    coverage_epoch: Mapped[int] = mapped_column(Integer, default=0)
    parent_exam_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("exams.id", ondelete="SET NULL"), nullable=True
    )
    # "All items": every item in the scope, reviewed or not; a question that can't be made hint-free
    # gets the least-hinting options instead of being skipped.
    all_items: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    status: Mapped[str] = mapped_column(String(16), default="generating")  # generating|ready|failed
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    step_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    reviewer: Mapped[Reviewer] = relationship(back_populates="exams")
    questions: Mapped[list["Question"]] = relationship(
        back_populates="exam", cascade="all, delete-orphan", order_by="Question.position"
    )
    attempts: Mapped[list["Attempt"]] = relationship(
        back_populates="exam", cascade="all, delete-orphan", order_by="Attempt.attempt_no"
    )

    @property
    def shortfall(self) -> int:
        return max(0, self.requested_count - self.actual_count) if self.status == "ready" else 0


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    exam_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    source_item_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("source_items.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(16))  # mcq | true_false | identification
    position: Mapped[int] = mapped_column(Integer)
    prompt: Mapped[str] = mapped_column(Text)
    choices: Mapped[list | None] = mapped_column(JSON, nullable=True)
    correct_answer: Mapped[str] = mapped_column(Text)
    accepted_answers: Mapped[list] = mapped_column(JSON, default=list)
    rationale: Mapped[str] = mapped_column(Text, default="")
    choice_feedback: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    explanation: Mapped[dict] = mapped_column(JSON, default=dict)

    exam: Mapped[Exam] = relationship(back_populates="questions")
    source_item: Mapped[SourceItem] = relationship()


# ---------------------------------------------------------------- attempts


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    exam_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    attempt_no: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16), default="full")  # full | mistakes
    source_attempt_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("attempts.id", ondelete="SET NULL"), nullable=True
    )
    question_order: Mapped[list] = mapped_column(JSON, default=list)
    choice_orders: Mapped[dict] = mapped_column(JSON, default=dict)
    last_viewed_index: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="in_progress")  # in_progress|completed
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    exam: Mapped[Exam] = relationship(back_populates="attempts")
    answers: Mapped[list["Answer"]] = relationship(
        back_populates="attempt", cascade="all, delete-orphan"
    )


class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (UniqueConstraint("attempt_id", "question_id", name="uq_answers_attempt_q"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    attempt_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("attempts.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    response: Mapped[str] = mapped_column(Text)
    is_correct: Mapped[bool] = mapped_column(Boolean)
    match_note: Mapped[str | None] = mapped_column(String(32), nullable=True)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    attempt: Mapped[Attempt] = relationship(back_populates="answers")
    question: Mapped[Question] = relationship()
