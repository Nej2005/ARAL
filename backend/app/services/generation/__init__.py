from dataclasses import dataclass, field

from app.models import Document, SourceItem

QUESTION_TYPES = ("mcq", "true_false", "identification")
TYPE_ORDER = {t: i for i, t in enumerate(QUESTION_TYPES)}


@dataclass
class Draft:
    """A question being built; becomes a `Question` row once it passes the fidelity checks."""

    ref: str
    type: str
    item: SourceItem
    doc: Document
    prompt: str = ""
    choices: list[dict] | None = None
    correct_answer: str = ""
    accepted_answers: list[str] = field(default_factory=list)
    rationale: str = ""
    choice_feedback: dict | None = None
    explanation: dict = field(default_factory=dict)
    # true/false
    is_true: bool | None = None
    # mcq
    mcq_format: str | None = None  # "fill_in" | "term_meaning"
    candidate_ids: list[str] = field(default_factory=list)
    needs_generated: int = 0
    failed: str | None = None


def source_ref(doc: Document, page_no: int) -> str:
    return f"{doc.filename}, {doc.page_label(page_no)}"
