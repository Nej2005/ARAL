from dataclasses import dataclass


@dataclass
class ExtractedPage:
    page_no: int
    title: str | None
    text: str
