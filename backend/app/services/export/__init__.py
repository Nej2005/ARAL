from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from app.config import BACKEND_DIR

FONT_DIR = BACKEND_DIR / "app" / "assets" / "fonts"

TYPE_LABEL = {"mcq": "Multiple Choice", "true_false": "True or False", "identification": "Identification"}
TYPE_INSTRUCTION = {
    "mcq": "Choose the letter of the best answer.",
    "true_false": "Write TRUE if the statement is correct and FALSE if it is not.",
    "identification": "Write the term being described.",
}


class ReviewerPDF(FPDF):
    """A4 portrait with the bundled Unicode font, so ñ, é, – and • all render."""

    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.add_font("Noto", "", Path(FONT_DIR / "NotoSans-Regular.ttf"))
        self.add_font("Noto", "B", Path(FONT_DIR / "NotoSans-Bold.ttf"))
        self.set_auto_page_break(auto=True, margin=18)
        self.set_margins(18, 18, 18)
        self.alias_nb_pages()

    def footer(self):
        self.set_y(-12)
        self.set_font("Noto", "", 8)
        self.set_text_color(120)
        self.cell(0, 6, f"Page {self.page_no()}/{{nb}}", align="C", new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.set_text_color(0)

    # --- small helpers -------------------------------------------------
    def text_line(self, text: str, size: float = 10.5, bold: bool = False, indent: float = 0, h: float = 5.5):
        self.set_font("Noto", "B" if bold else "", size)
        x = self.l_margin + indent
        self.set_x(x)
        self.multi_cell(self.w - self.r_margin - x, h, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def heading(self, text: str, size: float = 13):
        self.ln(2)
        self.set_font("Noto", "B", size)
        self.multi_cell(0, 7, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)

    def rule(self):
        y = self.get_y() + 1
        self.line(self.l_margin, y, self.w - self.r_margin, y)
        self.ln(3)
