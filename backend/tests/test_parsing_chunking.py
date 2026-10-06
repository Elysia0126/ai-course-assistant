from pathlib import Path

import pytest

from app.core.errors import DocumentParsingError
from app.services.chunking import chunk_document, split_text
from app.services.parsing import ParsedDocument, ParsedSection, parse_document
from tests import factories


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_pdf_sections_keep_page_numbers(tmp_path: Path) -> None:
    parsed = parse_document(_write(tmp_path, "a.pdf", factories.make_pdf()), "pdf")
    assert parsed.page_count == 3
    assert [s.page_number for s in parsed.sections] == [1, 2, 3]
    assert parsed.sections[1].section == "Learning Rate Schedules"
    assert "Warmup is a technique" in parsed.sections[1].text


def test_pptx_includes_titles_bullets_and_speaker_notes(tmp_path: Path) -> None:
    parsed = parse_document(_write(tmp_path, "a.pptx", factories.make_pptx()), "pptx")
    assert parsed.page_count == 2
    first = parsed.sections[0]
    assert first.page_number == 1 and first.section == "Backpropagation"
    assert "chain rule" in first.text
    assert "Speaker notes: It runs backwards" in first.text


def test_docx_splits_on_headings(tmp_path: Path) -> None:
    parsed = parse_document(_write(tmp_path, "a.docx", factories.make_docx()), "docx")
    assert [s.section for s in parsed.sections] == ["Dropout", "Early Stopping"]


def test_markdown_tracks_heading_path(tmp_path: Path) -> None:
    parsed = parse_document(_write(tmp_path, "a.md", factories.MARKDOWN), "md")
    sections = [s.section for s in parsed.sections]
    assert sections[0] == "Regularization"
    assert "Dropout" in sections


def test_blank_pdf_raises_helpful_error(tmp_path: Path) -> None:
    with pytest.raises(DocumentParsingError, match="scanned PDF"):
        parse_document(_write(tmp_path, "blank.pdf", factories.make_blank_pdf()), "pdf")


def test_corrupt_file_raises_parsing_error(tmp_path: Path) -> None:
    with pytest.raises(DocumentParsingError, match="corrupted"):
        parse_document(_write(tmp_path, "bad.pptx", b"PK\x03\x04not really a zip"), "pptx")


def test_split_text_respects_size_and_overlap() -> None:
    sentences = [f"Sentence number {i} talks about gradient descent and learning rates." for i in range(40)]
    text = " ".join(sentences)
    chunks = split_text(text, chunk_size=300, chunk_overlap=80)
    assert len(chunks) > 5
    assert all(len(c) <= 300 for c in chunks)
    # Consecutive chunks share the overlapping tail sentence.
    assert chunks[0].splitlines()[-1] in chunks[1]


def test_split_text_handles_giant_tokens() -> None:
    chunks = split_text("x" * 2500, chunk_size=1000, chunk_overlap=100)
    assert all(len(c) <= 1000 for c in chunks)
    assert "".join(chunks).count("x") >= 2500


def test_chunks_never_cross_pages() -> None:
    parsed = ParsedDocument(
        sections=[ParsedSection("alpha " * 300, page_number=1), ParsedSection("beta " * 300, page_number=2)]
    )
    chunks = chunk_document(parsed, chunk_size=500, chunk_overlap=50)
    assert {c.page_number for c in chunks if "alpha" in c.content} == {1}
    assert {c.page_number for c in chunks if "beta" in c.content} == {2}
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_chunk_overlap_must_be_smaller_than_size() -> None:
    with pytest.raises(ValueError):
        chunk_document(ParsedDocument(sections=[ParsedSection("text")]), chunk_size=100, chunk_overlap=100)
