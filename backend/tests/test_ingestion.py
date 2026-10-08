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
