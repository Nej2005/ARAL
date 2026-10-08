"""Same-file and same-text detection (BACKEND.md §5.5)."""

from __future__ import annotations

import hashlib
from typing import BinaryIO

from app.services.fidelity import norm_cmp


def sha256_stream(f: BinaryIO, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    while True:
        b = f.read(chunk)
        if not b:
            break
        h.update(b)
    return h.hexdigest()


def text_sha256(page_texts: list[str]) -> str:
    joined = "\n\f\n".join(norm_cmp(t) for t in page_texts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
