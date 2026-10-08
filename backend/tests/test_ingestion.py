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
