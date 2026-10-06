"""Structure-aware chunking.

Sections (pages, slides, headings) are split independently, so a chunk never straddles two pages and
its citation location is always exact. Inside a section we split on paragraphs, then sentences, then
words, packing pieces greedily up to ``chunk_size`` characters with a tail overlap between chunks.
"""

from dataclasses import dataclass

from app.services.parsing import ParsedDocument
from app.services.text_utils import split_sentences

MIN_CHUNK_CHARS = 20


@dataclass
class ChunkDraft:
    chunk_index: int
    content: str
    page_number: int | None
    section: str | None


def chunk_document(parsed: ParsedDocument, chunk_size: int, chunk_overlap: int) -> list[ChunkDraft]:
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    drafts: list[ChunkDraft] = []
    for section in parsed.sections:
        for piece in split_text(section.text, chunk_size, chunk_overlap):
            if len(piece) < MIN_CHUNK_CHARS:
                continue
            drafts.append(
                ChunkDraft(
                    chunk_index=len(drafts),
                    content=piece,
                    page_number=section.page_number,
                    section=section.section,
                )
            )
    return drafts


def split_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    text = text.strip()
    if len(text) <= chunk_size:
        return [text] if text else []

    units = _atomic_units(text, chunk_size)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for unit in units:
        added = len(unit) + (1 if current else 0)
        if current and current_len + added > chunk_size:
            chunks.append(_join(current))
            current, current_len = _overlap_tail(current, chunk_overlap)
            added = len(unit) + (1 if current else 0)
        current.append(unit)
        current_len += added

    if current:
        chunks.append(_join(current))
    return chunks


def _atomic_units(text: str, chunk_size: int) -> list[str]:
    """Break text into pieces no longer than chunk_size, preferring natural boundaries:
    paragraphs, then sentences, then lines (bullet lists), then words."""
    units: list[str] = []
    for paragraph in (p.strip() for p in text.split("\n\n")):
        if not paragraph:
            continue
        if len(paragraph) <= chunk_size:
            units.append(paragraph)
            continue
        for sentence in split_sentences(paragraph):
            if len(sentence) <= chunk_size:
                units.append(sentence)
                continue
            for line in (ln.strip() for ln in sentence.split("\n")):
                if not line:
                    continue
                units.extend([line] if len(line) <= chunk_size else _split_words(line, chunk_size))
    return units


def _split_words(text: str, chunk_size: int) -> list[str]:
    pieces: list[str] = []
    current = ""
    for word in text.split():
        while len(word) > chunk_size:  # pathological tokens such as long URLs or CJK runs
            if current:
                pieces.append(current)
                current = ""
            pieces.append(word[:chunk_size])
            word = word[chunk_size:]
        candidate = f"{current} {word}".strip()
        if len(candidate) > chunk_size:
            pieces.append(current)
            current = word
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def _overlap_tail(units: list[str], overlap: int) -> tuple[list[str], int]:
    """Carry the last few units (up to ``overlap`` chars) into the next chunk for context continuity."""
    if overlap <= 0:
        return [], 0
    tail: list[str] = []
    length = 0
    for unit in reversed(units):
        extra = len(unit) + (1 if tail else 0)
        if length + extra > overlap:
            break
        tail.insert(0, unit)
        length += extra
    return tail, length


def _join(units: list[str]) -> str:
    return "\n".join(units)
