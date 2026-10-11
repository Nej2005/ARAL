from app.services.ingestion.dedupe import text_sha256
from app.services.ingestion.pdf import extract_pdf
from app.services.ingestion.pptx import extract_pptx


def test_pptx_slides_titles_bullets_and_tables(fixture_files):
    pages = extract_pptx(fixture_files["pptx"])
    assert len(pages) == 5
    assert pages[0].title == "Photosynthesis"
    assert pages[0].text.splitlines()[0] == "Photosynthesis"
    assert "• Photosynthesis – the process by which green plants" in pages[0].text
    assert pages[1].title == "Photosynthesis (cont.)"
    table = pages[4]
    assert table.title == "Key Terms"
    assert "Carotenoids | accessory pigments" in table.text


def test_pdf_pages_drop_repeated_header_and_page_numbers(fixture_files):
    pages = extract_pdf(fixture_files["pdf"])
    assert len(pages) == 4
    for p in pages:
        assert "BIO 101" not in p.text, p.text
        assert not p.text.rstrip().endswith(f"Page {p.page_no}")
    assert pages[0].title == "Cellular Respiration"
    assert "The mitochondria is known as the powerhouse of the cell." in pages[0].text


def test_text_hash_ignores_whitespace_and_case():
    assert text_sha256(["Hello  World\n"]) == text_sha256(["hello world"])
    assert text_sha256(["a"]) != text_sha256(["b"])


GLOSSARY = """# Terms

## Shared Folders

- **Server Message Block (SMB)** - Originally developed by IBM, SMB is the default file sharing protocol used by Windows systems
- **Read-only attribute**
    - changes to its contents cannot be saved to the same file name
    - it applies to existing files within the folder only
- **Built-in SYSTEM group** - (represents operating system components)

### SMB shared folder permissions

- **Read** - Allows groups or users to read and execute files.
    - Applies to: Folders and files
- **hard quota / soft quota** - Folder quotas can block files after a limit (called a hard quota) or allow it (called a soft quota).
- **Read/Write** - Allows groups or users to read, execute, delete, and modify files.
"""


def test_markdown_term_list_is_read_word_for_word():
    from app.services.ingestion.markdown import parse_markdown

    pages, entries = parse_markdown(GLOSSARY)
    assert [p.title for p in pages] == ["Shared Folders", "SMB shared folder permissions"]
    by = {e.term: e for e in entries}
    assert set(by) == {"Server Message Block (SMB)", "Read-only attribute", "Built-in SYSTEM group", "Read",
                       "hard quota", "soft quota", "Read/Write"}  # "a / b" split, "Read/Write" kept
    assert by["Read"].body == "Allows groups or users to read and execute files."  # "Applies to" ignored
    assert by["Read"].topic == "SMB shared folder permissions"
    assert by["Built-in SYSTEM group"].body == "represents operating system components"
    assert by["Read-only attribute"].body == ("changes to its contents cannot be saved to the same file name; "
                                             "it applies to existing files within the folder only.")
    for e in entries:  # every quote is real text of its section
        assert e.quote in pages[e.page_no - 1].text, e.term


def test_answer_key_quiz_is_read_as_written(tmp_path):
    from app.services.ingestion.quiz import answer_text, read_quiz_pdf
    from tests.fixtures import build_quiz_pdf

    qs = read_quiz_pdf(build_quiz_pdf(tmp_path / "quiz.pdf"))
    assert [q.number for q in qs] == [1, 2, 3, 4, 5]
    assert qs[0].choices == ["NTFS", "ReFS", "FAT32", "exFAT"] and qs[0].correct == [2, 3]  # two bold answers
    assert answer_text(qs[0].answer_key()) == "C) FAT32; D) exFAT"
    assert qs[1].question.endswith("cannot delete, write over, or modify data?")  # wrapped line joined
    assert qs[1].correct == [0]
    assert qs[2].choices[-1] == "Both a and c" and qs[2].correct == [3]
    assert qs[3].type == "true_false" and qs[3].answer == "false" and qs[3].section == "True or False"
    assert qs[4].answer == "true"


def test_a_lesson_pdf_is_not_a_quiz(fixture_files):
    from app.services.ingestion.quiz import read_quiz_pdf

    assert read_quiz_pdf(fixture_files["pdf"]) == []


def _l(text, bold=False, x=20.0, page=1):
    return (page, text, bold, x)


def test_quiz_parser_edge_cases():
    from app.services.ingestion.quiz import parse_quiz_lines

    # an outline with every sub-item bold is not a quiz
    outline = [_l("1. Types of encryption"), _l("a) Symmetric", True, 30), _l("b) Asymmetric", True, 30)] * 3
    assert parse_quiz_lines(outline) == []

    # numbering that restarts keeps both parts; a page header between choices doesn't cut a question
    lines = [
        _l("1. First question?"), _l("A) One", False, 30), _l("Quiz 12/26", False, 10, 2),
        _l("B) Two", True, 30, 2), _l("C) Three", False, 30, 2),
        _l("Test II", False, 10), _l("1. A statement."), _l("True", True, 30),
        _l("2. A long right answer?"), _l("A) Short", False, 30), _l("B) The right one that", True, 30),
        _l("wraps onto the next line", True, 34), _l("C) Other", False, 30),
    ]
    qs = parse_quiz_lines(lines)
    assert [(q.number, q.seq) for q in qs] == [(1, 1), (1, 2), (2, 3)]
    assert qs[0].choices == ["One", "Two", "Three"] and qs[0].correct == [1]
    assert qs[1].type == "true_false" and qs[1].section == "Test II"
    assert qs[2].choices[1] == "The right one that wraps onto the next line" and qs[2].correct == [1]
