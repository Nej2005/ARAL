"""Optional exam scope: certain files, page ranges and/or topics (BACKEND.md §7.2)."""

from __future__ import annotations

from app.errors import AppError
from app.models import Document, SourceItem
from app.services.fidelity import topic_key


def normalize_scope(scope: dict | None) -> dict | None:
    """Return a canonical scope dict, or None when it means "the whole reviewer"."""
    if not scope:
        return None
    docs = []
    for d in scope.get("documents") or []:
        entry = {"document_id": d["document_id"]}
        pages = d.get("pages")
        if pages:
            entry["pages"] = [[int(a), int(b)] for a, b in pages]
        docs.append(entry)
    topics = [t for t in (scope.get("topics") or []) if t and str(t).strip()]
    if not docs and not topics:
        return None
    out: dict = {}
    if docs:
        out["documents"] = docs
    if topics:
        out["topics"] = [str(t) for t in topics]
    return out


def validate_scope(scope: dict | None, documents: list[Document], topic_keys: set[str]) -> dict | None:
    scope = normalize_scope(scope)
    if scope is None:
        return None
    by_id = {d.id: d for d in documents}
    for d in scope.get("documents", []):
        doc = by_id.get(d["document_id"])
        if doc is None:
            raise AppError(422, "INVALID_SCOPE", "A document in the scope is not part of this reviewer.",
                           document_id=d["document_id"])
        for a, b in d.get("pages", []):
            if a < 1 or b < a or b > max(doc.page_count, 1):
                raise AppError(422, "INVALID_SCOPE",
                               f"Page range {a}-{b} is outside {doc.filename} (1-{doc.page_count}).",
                               document_id=doc.id)
    for t in scope.get("topics", []):
        if topic_key(t) not in topic_keys:
            raise AppError(422, "INVALID_SCOPE", f"Topic '{t}' does not exist in this reviewer.", topic=t)
    return scope


def item_in_scope(item: SourceItem, scope: dict | None) -> bool:
    if scope is None:
        return True
    docs = scope.get("documents")
    if docs:
        entry = next((d for d in docs if d["document_id"] == item.document_id), None)
        if entry is None:
            return False
        ranges = entry.get("pages")
        if ranges and not any(a <= item.page_no <= b for a, b in ranges):
            return False
    topics = scope.get("topics")
    if topics:
        keys = {topic_key(t) for t in topics}
        if item.topic_key not in keys:
            return False
    return True


def filter_items(items: list[SourceItem], scope: dict | None) -> list[SourceItem]:
    return [i for i in items if item_in_scope(i, scope)]
