"""Uploaded files live in the database (table `document_files`), never on disk.

The readers (PyMuPDF, python-pptx, LibreOffice) want a path, so `materialized()` writes the bytes
to a temp file for the duration of one step and removes it afterwards. This works the same on
localhost and on a serverless host where only /tmp is writable.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Document, DocumentFile

MAGIC = {"pdf": (b"%PDF",), "pptx": (b"PK\x03\x04",), "ppt": (b"\xd0\xcf\x11\xe0",)}


def looks_like(file_type: str, head: bytes) -> bool:
    return any(head.startswith(m) for m in MAGIC[file_type])


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_file(db: Session, doc: Document, data: bytes) -> None:
    existing = db.get(DocumentFile, doc.id)
    if existing is None:
        db.add(DocumentFile(document_id=doc.id, data=data, size=len(data)))
    else:
        existing.data = data
        existing.size = len(data)
    doc.size = len(data)


def drop_file(db: Session, doc: Document) -> None:
    """Called once the pages are stored: the original bytes are no longer needed."""
    f = db.get(DocumentFile, doc.id)
    if f is not None:
        db.delete(f)


def has_file(db: Session, doc: Document) -> bool:
    return db.get(DocumentFile, doc.id) is not None


@contextmanager
def materialized(db: Session, doc: Document) -> Iterator[Path]:
    f = db.get(DocumentFile, doc.id)
    if f is None:
        raise FileNotFoundError(f"document {doc.id} has no stored file")
    tmpdir = Path(tempfile.mkdtemp(prefix="aral_"))
    path = tmpdir / f"original.{doc.file_type}"
    path.write_bytes(f.data)
    try:
        yield path
    finally:
        for p in tmpdir.iterdir():
            try:
                p.unlink()
            except OSError:
                pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass
